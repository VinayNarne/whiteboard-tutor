"""
core/events.py
Fixed Event Vocabulary Constants for Learning Platform.
"""


class EngineEvent:
    DRAW_STARTED = "draw_started"
    DRAW_COMPLETED = "draw_completed"
    DRAW_FAILED = "draw_failed"
    MODIFY_STARTED = "modify_started"
    MODIFY_COMPLETED = "modify_completed"
    SANITIZE_FAILED = "sanitize_failed"
    GEOMETRY_INVALID = "geometry_invalid"
    DENSITY_SOFT_SIGNAL = "density_soft_signal"
    DENSITY_HARD_CAP = "density_hard_cap"
    DENSITY_CHECKED = "density_checked"       # one per drawn element: page element count and canvas fill
    EMPTY_REPLY = "empty_reply"               # the model's final text was empty or whitespace (tool_call_succeeded in data: the board changed this turn or not)
    MODEL_USAGE = "model_usage"               # one per model call: prompt/completion tokens (cost visibility)
    TOOL_CALL = "tool_call"                   # one per tool the model calls: which tool, for which element
    MARKER_REPAIRED = "marker_repaired"       # a narration's [[MARK:id]] was missing or wrongly written and the code fixed it (reasons in data)
    GROUP_REPAIRED = "group_repaired"         # a drawing was not exactly one <g id=element_id> and the code wrapped it (reason in data)
    CONTROL_CHARS_REPLACED = "control_chars_replaced"   # the sanitiser replaced control characters in model SVG by a visible placeholder (count in data)
    ATTRIBUTE_REPAIRED = "attribute_repaired" # the sanitiser repaired font-size"20" (missing equals sign), one event per repair
    CONTENT_LOST = "content_lost"             # part of what the model drew did not reach the board; the tutor was told (what was lost in data)
    OVERLAP_CAP_REACHED = "overlap_cap_reached"             # the same element was rejected for overlapping the same element twice already in this turn: only the free-region hint is sent now
    LOST_CONTENT_CAP_REACHED = "lost_content_cap_reached"   # the lost-content note was already told twice for this element in this turn: the tutor is not told again (element, count in data)
    ITERATION_LIMIT_REACHED = "iteration_limit_reached"     # the tutor loop used all 20 model calls of a turn without a final answer; the learner gets the canned reply
    UNLABELED_CARD_NOTE = "unlabeled_card_note"   # a drawing has a card-sized rectangle and no text (was a rejection, now a note)
    TEXT_WIDTH_NOTE = "text_width_note"       # LOG ONLY (not shown to the tutor): a label's estimated width runs past its card, off the canvas or into another element
    LAYOUT_HINT = "layout_hint"               # an advisory hint (unlabeled card / empty container) shown to the tutor
    SHADOW_VALIDATED = "shadow_validated"     # LOG ONLY: what the proposed shape-level validator would decide for a drawing, next to the existing checks (engine/shadow.py); changes nothing
    SHADOW_SKIPPED = "shadow_skipped"         # LOG ONLY: the shadow check took longer than its time limit and was abandoned
    SHADOW_FAILED = "shadow_failed"           # LOG ONLY: the shadow check raised an error (caught; the drawing was not affected)
    AUDIO_SYNTHESIS_STARTED = "audio_synthesis_started"
    AUDIO_SYNTHESIS_COMPLETED = "audio_synthesis_completed"
    AUDIO_SYNTHESIS_FAILED = "audio_synthesis_failed"
    ANNOTATE_STARTED = "annotate_started"
    ANNOTATE_COMPLETED = "annotate_completed"
    ANNOTATE_FAILED = "annotate_failed"
    SCENE_DRAWN = "scene_drawn"               # scene mode: a draw_scene was laid out and published (scale, steps, geometry issues in data)
    SCENE_REJECTED = "scene_rejected"         # scene mode: a draw_scene could not be drawn; the reason went back to the tutor


class BackendEvent:
    SERVER_STARTUP = "server_startup"
    SERVER_SHUTDOWN = "server_shutdown"
    NOTEBOOK_CREATED = "notebook_created"
    NOTEBOOK_DELETED = "notebook_deleted"
    PAGE_CREATED = "page_created"
    PAGE_DELETED = "page_deleted"
    PAGE_SAVED = "page_saved"
    PAGE_SUMMARISED = "page_summarised"       # the cheap model wrote the summary of a page that was just saved
    PAGE_SUMMARY_FAILED = "page_summary_failed"   # it could not (timeout, error, empty reply): the page is saved without a summary
    LESSON_PLANNED = "lesson_planned"         # scene mode: the private lesson plan was written (or the message was not a learning request: chars 0)
    LESSON_PLAN_FAILED = "lesson_plan_failed" # it could not be written: the tutor teaches without one, the next question tries again
    DB_CONNECTED = "db_connected"
    DB_DISCONNECTED = "db_disconnected"
    CHAT_RECEIVED = "chat_received"
    CHAT_COMPLETED = "chat_completed"
    CONTEXT_BUILT = "context_built"           # per chat turn: how many earlier pages, how many show a summary in the tutor's context, how many history turns (eval M reads it)
    CLIENT_ERROR = "client_error"             # the browser reported an error: uncaught exception, rejected promise, console.error/warn, failed API call (frontend/src/utils/clientLog.ts)
    CHAT_FAILED = "chat_failed"               # a chat turn ended without an answer (model unreachable, or an unexpected error); the turn is stored as failed


class SessionEvent:
    ELEMENT_DRAWN = "element_drawn"
    ELEMENT_MODIFIED = "element_modified"
    ELEMENT_REMOVED = "element_removed"
    ELEMENT_ANNOTATED = "element_annotated"
    ANNOTATION_REMOVED = "annotation_removed"
    PAGE_DENSITY_NUDGE = "page_density_nudge"
    PAGE_DENSITY_HARD_CAP = "page_density_hard_cap"
    PAGE_SAVED = "page_saved"
    PAGE_STARTED = "page_started"
    CHAT_TURN = "chat_turn"
    BARGE_IN = "barge_in"
    ERROR = "error"
