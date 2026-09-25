"""Moteur de la file : état des tâches + workers en arrière-plan.

- 2 threads « infos » (métadonnées, toujours actifs, même file en pause),
- 1 thread « téléchargement », 1 thread « découpe » (actifs quand la file tourne).

Toutes les données sont modifiées sous ``self._lock`` ; les opérations longues
(réseau, FFmpeg) s'exécutent hors verrou. L'interface envoie des commandes
(méthodes publiques, non bloquantes) et reçoit des événements via ``emit``.
"""

import contextlib
import copy
import logging
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from ytb_edit.core import scheduling
from ytb_edit.core.errors import (
    AppError,
    MissingStreamError,
    OperationCancelled,
    SourceCorruptedError,
)
from ytb_edit.core.events import (
    Event,
    Notice,
    Progress,
    QueueIdle,
    QueueStateChanged,
    Summary,
    TaskChanged,
    TaskRemoved,
)
from ytb_edit.core.models import (
    AudioFormat,
    OutputMode,
    Segment,
    SegmentStatus,
    SourceFiles,
    TaskStatus,
    VideoInfo,
    VideoTask,
    check_transition,
)
from ytb_edit.core.segments import validate_segment
from ytb_edit.services import files
from ytb_edit.services.cache import SourceCache
from ytb_edit.services.youtube import canonical_url, parse_video_id

log = logging.getLogger(__name__)

INTERNAL_ERROR = "Erreur interne (voir les logs)."
PROGRESS_INTERVAL_S = 0.2
DOWNLOAD_MARGIN_BYTES = 200 * 1024 * 1024


@dataclass(frozen=True)
class CutRequest:
    source: SourceFiles
    mode: OutputMode
    start_s: int
    end_s: int
    output: Path
    container: str


class Media(Protocol):
    """Opérations externes utilisées par le moteur (remplaçables par des faux en test)."""

    def fetch_info(self, video_id: str) -> VideoInfo: ...

    def download(
        self,
        info: VideoInfo,
        dest_dir: Path,
        *,
        want_video: bool,
        want_audio: bool,
        prefer_aac: bool,
        is_cancelled: Callable[[], bool],
        on_progress: Callable[[float, str], None],
    ) -> SourceFiles: ...

    def validate_source(self, source: SourceFiles, info: VideoInfo) -> None: ...

    def output_container(
        self, source: SourceFiles, mode: OutputMode, audio_format: AudioFormat
    ) -> str: ...

    def cut(
        self,
        request: CutRequest,
        *,
        is_cancelled: Callable[[], bool],
        on_progress: Callable[[float], None],
    ) -> float: ...


@dataclass
class EngineConfig:
    output_dir: Path | None = None
    audio_format: AudioFormat = AudioFormat.M4A
    cache_limit_bytes: int = 20 * 1024**3
    keep_cache_on_exit: bool = False


class Engine:
    def __init__(
        self,
        media: Media,
        cache: SourceCache,
        emit: Callable[[Event], None],
        config: EngineConfig | None = None,
        *,
        info_workers: int = 2,
    ) -> None:
        self._media = media
        self._cache = cache
        self._emit_cb = emit
        self._config = config or EngineConfig()
        self._info_workers = info_workers

        self._lock = threading.RLock()
        self._cond = threading.Condition(self._lock)
        self._tasks: list[VideoTask] = []
        self._running = False
        self._stopping = False
        self._threads: list[threading.Thread] = []
        self._info_in_flight: set[str] = set()
        self._busy: set[str] = set()  # tâches avec un téléchargement/découpe en cours
        self._delete_when_idle: set[str] = set()  # video_id à supprimer du cache
        self._cancel: dict[str, threading.Event] = {}  # par tâche et par segment
        self._active_jobs = 0
        self._had_activity = False
        self._completed_order: list[str] = []
        self._cut_attempts: dict[str, int] = {}
        self._last_progress: dict[str, float] = {}

    # ------------------------------------------------------------------ cycle de vie

    def start_workers(self) -> None:
        kinds = ["info"] * self._info_workers + ["download", "cut"]
        for index, kind in enumerate(kinds):
            thread = threading.Thread(
                target=self._loop, args=(kind,), daemon=True, name=f"{kind}-{index}"
            )
            thread.start()
            self._threads.append(thread)

    def shutdown(self, timeout: float = 5.0) -> None:
        """Arrête proprement : annule tout, attend les workers, nettoie le cache."""
        with self._cond:
            self._stopping = True
            for event in self._cancel.values():
                event.set()
            self._cond.notify_all()
            video_ids = [t.info.video_id for t in self._tasks if t.info]
        deadline = time.monotonic() + timeout
        for thread in self._threads:
            thread.join(max(0.0, deadline - time.monotonic()))
        if not self._config.keep_cache_on_exit:
            for video_id in video_ids:
                self._cache.delete(video_id)

    def configure(self, **changes: object) -> None:
        with self._cond:
            for key, value in changes.items():
                if not hasattr(self._config, key):
                    raise AttributeError(key)
                setattr(self._config, key, value)
            self._cond.notify_all()

    @property
    def running(self) -> bool:
        return self._running

    def is_busy(self) -> bool:
        with self._lock:
            return bool(self._busy)

    # ------------------------------------------------------------------ commandes

    def start(self) -> None:
        with self._cond:
            self._running = True
            self._emit(QueueStateChanged(True))
            self._cond.notify_all()

    def pause(self) -> None:
        """Aucune nouvelle opération ne démarre ; les opérations en cours se terminent."""
        with self._cond:
            self._running = False
            self._emit(QueueStateChanged(False))

    def add_video(self, url: str, mode: OutputMode) -> tuple[str, bool]:
        """Ajoute une vidéo. Renvoie ``(id, nouvelle)`` ; un doublon renvoie la tâche existante."""
        video_id = parse_video_id(url)  # lève InvalidUrlError
        canonical = canonical_url(video_id)
        with self._cond:
            for task in self._tasks:
                if task.url == canonical:
                    return task.id, False
            task = VideoTask(url=canonical, mode=mode)
            self._tasks.append(task)
            self._cancel[task.id] = threading.Event()
            self._changed(task)
            self._cond.notify_all()
            return task.id, True

    def add_segment(self, task_id: str, start_s: int, end_s: int) -> str:
        with self._cond:
            task = self._get(task_id)
            if task.info is None:
                raise AppError("Informations de la vidéo pas encore disponibles.")
            if task.status is TaskStatus.CANCELLED:
                raise AppError("Vidéo annulée : utilisez « Réessayer » avant d'ajouter un segment.")
            validate_segment(start_s, end_s, task.info.duration_s)
            segment = Segment(
                number=task.next_segment_number, start_s=start_s, end_s=end_s, mode=task.mode
            )
            task.next_segment_number += 1
            task.segments.append(segment)
            if task.status is TaskStatus.COMPLETED:
                self._reopen(task)
            self._changed(task)
            self._cond.notify_all()
            return segment.id

    def update_segment(self, task_id: str, segment_id: str, start_s: int, end_s: int) -> None:
        with self._cond:
            task = self._get(task_id)
            segment = self._get_segment(task, segment_id)
            if segment.status is not SegmentStatus.PENDING:
                raise AppError("Seul un segment en attente peut être modifié.")
            validate_segment(start_s, end_s, task.info.duration_s if task.info else None)
            segment.start_s, segment.end_s = start_s, end_s
            self._changed(task)

    def remove_segment(self, task_id: str, segment_id: str) -> None:
        with self._cond:
            task = self._get(task_id)
            segment = self._get_segment(task, segment_id)
            if segment.status is SegmentStatus.PROCESSING:
                raise AppError("Segment en cours de découpe : annulez-le d'abord.")
            task.segments.remove(segment)
            self._settle(task)
            self._changed(task)

    def set_mode(self, task_id: str, mode: OutputMode) -> None:
        """Change le mode de la vidéo ; s'applique aux segments encore en attente."""
        with self._cond:
            task = self._get(task_id)
            if task.info is not None:
                _check_mode_available(task.info, mode)
            task.mode = mode
            for segment in scheduling.pending_segments(task):
                segment.mode = mode
            self._changed(task)
            self._cond.notify_all()

    def cancel_task(self, task_id: str) -> None:
        with self._cond:
            task = self._get(task_id)
            if task.status in (TaskStatus.COMPLETED, TaskStatus.CANCELLED, TaskStatus.FAILED):
                return
            self._cancel[task.id].set()
            task.status = check_transition(task.status, TaskStatus.CANCELLED)
            for segment in task.segments:
                if segment.status is SegmentStatus.PENDING:
                    segment.status = SegmentStatus.CANCELLED
                elif segment.status is SegmentStatus.PROCESSING:
                    self._segment_event(segment).set()
            self._emit(Notice(f"⊘ {task.title} — annulée"))
            self._changed(task)
            self._cond.notify_all()

    def cancel_segment(self, task_id: str, segment_id: str) -> None:
        with self._cond:
            task = self._get(task_id)
            segment = self._get_segment(task, segment_id)
            if segment.status is SegmentStatus.PENDING:
                segment.status = SegmentStatus.CANCELLED
                self._settle(task)
            elif segment.status is SegmentStatus.PROCESSING:
                self._segment_event(segment).set()
            self._changed(task)

    def retry_task(self, task_id: str) -> None:
        """Relance une vidéo en échec/annulée, ou ses segments en échec/annulés."""
        with self._cond:
            task = self._get(task_id)
            self._cancel[task.id] = threading.Event()
            task.error = None
            for segment in task.segments:
                if segment.status in (SegmentStatus.FAILED, SegmentStatus.CANCELLED):
                    segment.status = SegmentStatus.PENDING
                    segment.error = None
                    self._cut_attempts.pop(segment.id, None)
            if task.status in (TaskStatus.FAILED, TaskStatus.CANCELLED):
                target = TaskStatus.FETCHING_INFO if task.info is None else TaskStatus.READY
                task.status = check_transition(task.status, target)
            elif task.status is TaskStatus.COMPLETED and scheduling.pending_segments(task):
                self._reopen(task)
            self._changed(task)
            self._cond.notify_all()

    def remove_task(self, task_id: str) -> None:
        """Retire la vidéo de la file (« Terminer ») et libère son cache."""
        with self._cond:
            task = self._find(task_id)
            if task is None:
                return
            self._cancel[task.id].set()
            for segment in task.segments:
                self._segment_event(segment).set()
            self._tasks.remove(task)
            video_id = task.info.video_id if task.info else None
            busy = task.id in self._busy
            if video_id and busy:
                self._delete_when_idle.add(video_id)
            self._emit(TaskRemoved(task.id))
            self._cond.notify_all()
        if video_id and not busy:
            self._cache.delete(video_id)

    def snapshot(self) -> list[VideoTask]:
        with self._lock:
            return copy.deepcopy(self._tasks)

    # ------------------------------------------------------------------ workers

    def _loop(self, kind: str) -> None:
        pick = getattr(self, f"_pick_{kind}")
        run = getattr(self, f"_run_{kind}")
        while True:
            with self._cond:
                while True:
                    if self._stopping:
                        return
                    job = pick()
                    if job is not None:
                        break
                    self._cond.wait(timeout=1.0)
                self._active_jobs += 1
            try:
                run(job)
            except Exception:  # dernier rempart : un worker ne meurt jamais
                log.exception("Erreur inattendue dans le worker %s", kind)
            finally:
                with self._cond:
                    self._active_jobs -= 1
                    self._check_idle()
                    self._cond.notify_all()

    # --- métadonnées

    def _pick_info(self) -> VideoTask | None:
        task = scheduling.next_info_task(self._tasks, self._info_in_flight)
        if task is not None:
            self._info_in_flight.add(task.id)
        return task

    def _run_info(self, task: VideoTask) -> None:
        try:
            info = self._media.fetch_info(parse_video_id(task.url))
        except Exception as exc:
            with self._cond:
                self._info_in_flight.discard(task.id)
                if self._alive(task, TaskStatus.FETCHING_INFO):
                    self._fail(task, exc)
            return
        with self._cond:
            self._info_in_flight.discard(task.id)
            if not self._alive(task, TaskStatus.FETCHING_INFO):
                return
            task.info = info
            try:
                _check_mode_available(info, task.mode)
            except MissingStreamError:
                task.mode = OutputMode.VIDEO_ONLY if info.has_video else OutputMode.AUDIO_ONLY
                missing = "audio" if info.has_video else "vidéo"
                self._emit(Notice(f"{info.title} : pas de piste {missing}, mode ajusté."))
            task.status = check_transition(task.status, TaskStatus.READY)
            self._changed(task)
            self._cond.notify_all()

    # --- téléchargement

    def _pick_download(self) -> VideoTask | None:
        if not self._running:
            return None
        task = scheduling.next_download_task(self._tasks)
        if task is not None:
            task.status = check_transition(task.status, TaskStatus.DOWNLOADING)
            task.download_progress = 0.0
            self._busy.add(task.id)
            self._had_activity = True
            self._changed(task)
        return task

    def _run_download(self, task: VideoTask) -> None:
        with self._lock:
            assert task.info is not None
            info = task.info
            want_video, want_audio = scheduling.missing_streams(task)
            current = task.source or SourceFiles()
            prefer_aac = (
                task.mode is OutputMode.AUDIO_ONLY and self._config.audio_format is AudioFormat.M4A
            )
            cancel = self._cancel[task.id]
        try:
            source = self._obtain_source(
                task.id, info, current, want_video, want_audio, prefer_aac, cancel
            )
        except OperationCancelled:
            log.info("Téléchargement annulé : %s", info.url)
            with self._cond:
                self._busy.discard(task.id)
                if self._alive(task, TaskStatus.DOWNLOADING) and not self._stopping:
                    task.status = check_transition(task.status, TaskStatus.CANCELLED)
                    self._changed(task)
            self._flush_deletions()
            return
        except Exception as exc:
            with self._cond:
                self._busy.discard(task.id)
                if self._alive(task, TaskStatus.DOWNLOADING):
                    self._fail(task, exc)
            self._flush_deletions()
            return
        with self._cond:
            self._busy.discard(task.id)
            if self._alive(task, TaskStatus.DOWNLOADING):
                task.source = source
                task.download_progress = 1.0
                task.status = check_transition(task.status, TaskStatus.DOWNLOADED)
                self._settle(task)
                self._changed(task)
                self._cond.notify_all()
        self._flush_deletions()

    def _obtain_source(
        self,
        task_id: str,
        info: VideoInfo,
        current: SourceFiles,
        want_video: bool,
        want_audio: bool,
        prefer_aac: bool,
        cancel: threading.Event,
    ) -> SourceFiles:
        merged = _merge(current, self._cache.load(info.video_id))
        want_video = want_video and merged.video_path is None
        want_audio = want_audio and merged.audio_path is None
        if not (want_video or want_audio):
            log.info("Source déjà en cache : %s", info.video_id)
            return merged

        dest = self._cache.dir_for(info.video_id)
        files.ensure_free_space(dest, int((info.estimated_size or 0) * 1.1) + DOWNLOAD_MARGIN_BYTES)

        def is_cancelled() -> bool:
            return cancel.is_set() or self._stopping

        for attempt in (1, 2):
            downloaded = self._media.download(
                info,
                dest,
                want_video=want_video,
                want_audio=want_audio,
                prefer_aac=prefer_aac,
                is_cancelled=is_cancelled,
                on_progress=lambda f, text: self._progress(task_id, f, text),
            )
            try:
                self._media.validate_source(downloaded, info)
                break
            except SourceCorruptedError:
                log.warning("Source invalide (tentative %s) : %s", attempt, downloaded)
                for path in (downloaded.video_path, downloaded.audio_path):
                    if path is not None:
                        path.unlink(missing_ok=True)
                if attempt == 2:
                    raise
        merged = _merge(merged, downloaded)
        self._cache.save(info.video_id, merged)
        return merged

    # --- découpe

    def _pick_cut(self) -> tuple[VideoTask, Segment] | None:
        if not self._running:
            return None
        job = scheduling.next_cut(self._tasks)
        if job is not None:
            task, segment = job
            task.status = check_transition(task.status, TaskStatus.PROCESSING)
            segment.status = check_transition(segment.status, SegmentStatus.PROCESSING)
            self._busy.add(task.id)
            self._had_activity = True
            self._changed(task)
        return job

    def _run_cut(self, job: tuple[VideoTask, Segment]) -> None:
        task, segment = job
        with self._lock:
            assert task.info is not None and task.source is not None
            info, source = task.info, task.source
            request_args = (segment.mode, segment.start_s, segment.end_s, segment.number)
            output_root = self._config.output_dir
            audio_format = self._config.audio_format
            task_cancel, segment_cancel = self._cancel[task.id], self._segment_event(segment)

        def is_cancelled() -> bool:
            return task_cancel.is_set() or segment_cancel.is_set() or self._stopping

        tmp: Path | None = None
        outcome: tuple[str, object] = ("error", INTERNAL_ERROR)
        try:
            mode, start_s, end_s, number = request_args
            if output_root is None:
                raise AppError("Aucun dossier de sortie choisi.")
            for path in (source.video_path, source.audio_path):
                if path is not None and not path.is_file():
                    raise SourceCorruptedError("Fichier source introuvable.", details=str(path))
            out_dir = files.video_output_dir(output_root, info.title, info.video_id)
            out_dir.mkdir(parents=True, exist_ok=True)
            container = self._media.output_container(source, mode, audio_format)
            name = files.clip_filename(
                number, start_s, end_s, with_hours=info.duration_s >= 3600, ext=container
            )
            final = files.unique_path(out_dir / name)
            tmp = final.with_name(f"{final.stem}.part.{container}")
            files.ensure_free_space(out_dir, _clip_size_estimate(source, info, end_s - start_s))
            actual = self._media.cut(
                CutRequest(source, mode, start_s, end_s, tmp, container),
                is_cancelled=is_cancelled,
                on_progress=lambda f: self._progress(task.id, f, f"Découpe du clip {number:03d}"),
            )
            final = files.unique_path(final)
            tmp.replace(final)
            tmp = None
            outcome = ("done", (final, actual))
        except OperationCancelled:
            outcome = ("cancelled", None)
        except SourceCorruptedError as exc:
            log.warning("Source inutilisable pour %s : %s", info.video_id, exc.details)
            outcome = ("corrupted", exc)
        except AppError as exc:
            log.warning("Échec de la découpe : %s (%s)", exc.user_message, exc.details)
            outcome = ("error", exc.user_message)
        except OSError as exc:
            log.exception("Erreur fichier pendant la découpe")
            outcome = ("error", f"Erreur d'écriture : {exc.strerror or exc}")
        except Exception:
            log.exception("Erreur inattendue pendant la découpe")
        finally:
            if tmp is not None:
                try:
                    tmp.unlink(missing_ok=True)
                except OSError:
                    log.warning("Fichier temporaire non supprimé : %s", tmp)
        self._finish_cut(task, segment, outcome)
        self._flush_deletions()

    def _finish_cut(self, task: VideoTask, segment: Segment, outcome: tuple[str, object]) -> None:
        kind, value = outcome
        with self._cond:
            self._busy.discard(task.id)
            removed = self._find(task.id) is not task
            if kind == "done":
                final, actual = value  # type: ignore[misc]
                segment.status = check_transition(segment.status, SegmentStatus.DONE)
                segment.output_path = final
                segment.actual_start_s = int(actual)
                segment.error = None
                if not removed:
                    self._emit(Notice(f"✓ {task.title} — {final.name}"))
            elif kind == "cancelled":
                target = SegmentStatus.PENDING if self._stopping else SegmentStatus.CANCELLED
                segment.status = check_transition(segment.status, target)
            elif kind == "corrupted":
                attempts = self._cut_attempts.get(segment.id, 0) + 1
                self._cut_attempts[segment.id] = attempts
                if attempts >= 2:
                    segment.status = check_transition(segment.status, SegmentStatus.FAILED)
                    segment.error = value.user_message  # type: ignore[attr-defined]
                else:
                    # Source à retélécharger : le segment reste en attente. Suppression
                    # immédiate, sinon le prochain téléchargement relirait le cache.
                    segment.status = check_transition(segment.status, SegmentStatus.PENDING)
                    if task.info and task.source is not None:
                        task.source = None
                        self._cache.delete(task.info.video_id)
            else:
                segment.status = check_transition(segment.status, SegmentStatus.FAILED)
                segment.error = str(value)
                if not removed:
                    self._emit(
                        Notice(f"✗ {task.title} — clip {segment.number:03d} : {value}", error=True)
                    )
            if not removed:
                if task.status is TaskStatus.PROCESSING:
                    task.status = check_transition(task.status, TaskStatus.DOWNLOADED)
                self._settle(task)
                self._changed(task)
            self._cond.notify_all()

    # ------------------------------------------------------------------ utilitaires

    def _settle(self, task: VideoTask) -> None:
        """DOWNLOADED sans segment en attente → COMPLETED (+ gestion du cache)."""
        if task.status is TaskStatus.DOWNLOADED and not scheduling.pending_segments(task):
            task.status = check_transition(task.status, TaskStatus.COMPLETED)
            done = task.count(SegmentStatus.DONE)
            failed = task.count(SegmentStatus.FAILED)
            text = f"{task.title} — terminée : {done} clip(s)"
            self._emit(
                Notice(
                    ("✓ " if not failed else "⚠ ")
                    + text
                    + (f", {failed} erreur(s)" if failed else ""),
                    error=bool(failed),
                )
            )
            if task.id in self._completed_order:
                self._completed_order.remove(task.id)
            self._completed_order.append(task.id)
            self._enforce_cache_limit(task)

    def _reopen(self, task: VideoTask) -> None:
        covered = task.source is not None and all(
            task.source.covers(s.mode) for s in scheduling.pending_segments(task)
        )
        target = TaskStatus.DOWNLOADED if covered else TaskStatus.READY
        task.status = check_transition(task.status, target)

    def _enforce_cache_limit(self, current: VideoTask) -> None:
        limit = self._config.cache_limit_bytes
        if limit <= 0 or self._cache.total_size() <= limit:
            return
        for task_id in list(self._completed_order):
            task = self._find(task_id)
            if task is None or task is current or task.status is not TaskStatus.COMPLETED:
                continue
            if task.info and task.source is not None:
                self._cache.delete(task.info.video_id)
                task.source = None
                log.info("Cache libéré (limite atteinte) : %s", task.info.video_id)
                self._changed(task)
                if self._cache.total_size() <= limit:
                    return

    def _flush_deletions(self) -> None:
        with self._lock:
            active = {t.info.video_id for t in self._tasks if t.info and t.id in self._busy}
            to_delete = self._delete_when_idle - active
            self._delete_when_idle -= to_delete
        for video_id in to_delete:
            self._cache.delete(video_id)

    def _fail(self, task: VideoTask, exc: BaseException) -> None:
        if isinstance(exc, AppError):
            message = exc.user_message
            log.warning("%s : %s (%s)", task.url, message, exc.details)
        else:
            message = INTERNAL_ERROR
            log.error("%s : erreur inattendue", task.url, exc_info=exc)
        task.status = check_transition(task.status, TaskStatus.FAILED)
        task.error = message
        self._emit(Notice(f"✗ {task.title} — {message}", error=True))
        self._changed(task)

    def _check_idle(self) -> None:
        if not self._running or not self._had_activity or self._active_jobs > 0:
            return
        if scheduling.next_download_task(self._tasks) or scheduling.next_cut(self._tasks):
            return
        self._had_activity = False
        self._emit(QueueIdle(self._summary()))

    def _summary(self) -> Summary:
        lines, videos, ok, clips, errors = [], 0, 0, 0, 0
        for task in self._tasks:
            if not task.segments and task.status is not TaskStatus.FAILED:
                continue
            videos += 1
            done = task.count(SegmentStatus.DONE)
            failed = task.count(SegmentStatus.FAILED)
            clips += done
            if task.status is TaskStatus.FAILED:
                errors += 1
                lines.append(f"✗ {task.title} — {task.error}")
            elif failed:
                errors += failed
                lines.append(f"⚠ {task.title} — {done} clip(s), {failed} erreur(s)")
            elif task.status is TaskStatus.CANCELLED:
                lines.append(f"⊘ {task.title} — annulée")
            else:
                ok += 1
                lines.append(f"✓ {task.title} — {done} clip(s)")
        return Summary(videos=videos, videos_ok=ok, clips=clips, errors=errors, lines=lines)

    def _progress(self, task_id: str, fraction: float, text: str) -> None:
        now = time.monotonic()
        if fraction < 1.0 and now - self._last_progress.get(task_id, 0.0) < PROGRESS_INTERVAL_S:
            return
        self._last_progress[task_id] = now
        with self._lock:
            task = self._find(task_id)
            if task is not None and task.status is TaskStatus.DOWNLOADING:
                task.download_progress = fraction
        self._emit(Progress(task_id, fraction, text))

    def _segment_event(self, segment: Segment) -> threading.Event:
        return self._cancel.setdefault(segment.id, threading.Event())

    def _alive(self, task: VideoTask, status: TaskStatus) -> bool:
        """La tâche est-elle toujours dans la file et dans l'état attendu ?"""
        return self._find(task.id) is task and task.status is status

    def _find(self, task_id: str) -> VideoTask | None:
        return next((t for t in self._tasks if t.id == task_id), None)

    def _get(self, task_id: str) -> VideoTask:
        task = self._find(task_id)
        if task is None:
            raise AppError("Vidéo introuvable dans la file.")
        return task

    @staticmethod
    def _get_segment(task: VideoTask, segment_id: str) -> Segment:
        segment = next((s for s in task.segments if s.id == segment_id), None)
        if segment is None:
            raise AppError("Segment introuvable.")
        return segment

    def _changed(self, task: VideoTask) -> None:
        self._emit(TaskChanged(copy.deepcopy(task)))

    def _emit(self, event: Event) -> None:
        try:
            self._emit_cb(event)
        except Exception:
            log.exception("Erreur lors de l'émission d'un événement")


def _check_mode_available(info: VideoInfo, mode: OutputMode) -> None:
    if mode.needs_audio and not info.has_audio:
        raise MissingStreamError("Cette vidéo n'a pas de piste audio.")
    if mode.needs_video and not info.has_video:
        raise MissingStreamError("Cette vidéo n'a pas de piste vidéo.")


def _merge(base: SourceFiles, extra: SourceFiles | None) -> SourceFiles:
    if extra is None:
        return base
    return SourceFiles(
        video_path=extra.video_path or base.video_path,
        audio_path=extra.audio_path or base.audio_path,
    )


def _clip_size_estimate(source: SourceFiles, info: VideoInfo, duration_s: int) -> int:
    total = 0
    for path in {source.video_path, source.audio_path} - {None}:
        with contextlib.suppress(OSError):
            total += path.stat().st_size  # type: ignore[union-attr]
    per_second = total / max(info.duration_s, 1)
    return int(per_second * (duration_s + 15) * 1.2) + 20 * 1024 * 1024
