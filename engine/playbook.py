"""
engine/playbook.py
Playbook: which teaching move the tutor uses for the learner's next turn (pure logic: no database, no web framework).
Measured in research_notes/Playbook/experiments/move_choice.md: the model chooses well only when code gives it the FACTS (concept level,
moves already tried, open misconception, intake); three objective vetoes then remove clearly wrong picks. Taste rules ("no stories when short
on time") made it worse, so there are exactly three vetoes and no more.

    facts_text(facts)                          -> the FACTS block of the selector prompt, as measured
    vetoes(facts, message)                     -> ids of the moves removed for this turn
    choose_move(step, topic, message, facts, chat, removed) -> {"move", "reason"}
facts: {"level", "tried": [(move, outcome), ...] oldest first, "misconception", "purpose", "time_budget", "self_level"}.
chat(system, user) -> the parsed JSON reply (a parameter so tests pass fakes).
"""
import json
import re
from typing import Callable, Iterable

from engine.author import AUTHOR_DEPLOYMENT, get_azure_client
from engine.summary import _clean_text

# id -> (label, what the tutor does, good when). From research_notes/Playbook/moves_v0.json.
MOVES = {
    "explain_direct": ("Explain directly", "short clear explanation + one diagram", "concept is new and the learner wants the basics"),
    "worked_example": ("Worked example", "a full example walked step by step", "learner is new and needs to see the whole procedure"),
    "faded_example": ("Faded example", "example where the learner completes the last steps", "learner has seen an example and is ready to try"),
    "socratic": ("Socratic questions", "lead with guiding questions", "learner has some grasp and can reason it out"),
    "predict_first": ("Predict first", "ask the learner to predict before teaching", "learner has some prior knowledge or a wrong belief to expose"),
    "analogy": ("Analogy", "compare with something familiar", "abstract concept, learner lacks a mental hook"),
    "story_case": ("Story or case", "a real scenario, case or short story", "motivation or context is needed"),
    "contrast": ("Contrast", "compare with a near concept or a non-example", "learner confuses it with something similar"),
    "retrieval_check": ("Retrieval check", "ask them to recall it from memory first", "concept was learned before and needs consolidation"),
    "teach_back": ("Teach back", "the learner explains it in their own words", "learner has just understood and should consolidate"),
    "misconception_first": ("Misconception first", "surface and correct a known wrong belief first", "learner holds a known wrong belief"),
    "challenge": ("Challenge", "a harder problem, edge case or trade-off", "learner has mastered the basics"),
    "big_picture": ("Big picture", "zoom out: where this fits and why it exists", "learner lacks context or is short on time"),
    "trace": ("Trace", "step through what actually happens, e.g. at runtime", "learner needs to see the mechanism in action"),
}
FALLBACK = ("explain_direct", "worked_example", "socratic")

# Intake: value -> (label shown to the learner, words the selector and the plan writer read).
INTAKE = {
    "purpose": {"curiosity": ("Curious", "just curious"), "exam": ("Exam", "preparing for an exam"),
                "work": ("Work / interview", "learning it for work or an interview"), "project": ("A project", "learning it for a project")},
    "time_budget": {"quick": ("Under 30 min", "under 30 minutes available"), "session": ("About an hour", "about an hour available"),
                    "course": ("Over several days", "several days available")},
    "self_level": {"new": ("New to me", "new to the topic"), "some": ("I know some", "knows some of it already"),
                   "comfortable": ("Comfortable", "comfortable with the topic")},
}

LEVEL_WORDS = {"new": "new to the learner", "taught": "taught, not yet answered correctly", "understood": "understood (graded right)",
               "remembered": "remembered (graded right in more than one turn)"}
OUTCOME_WORDS = {"right": "answer graded right", "partial": "answer graded partly right", "wrong": "answer graded wrong",
                 "pending": "no answer graded yet"}
EXPLAIN_DIFFERENTLY = re.compile(r"explain (it )?differently|another way|still (don't|do not) (get|understand)|don't understand|doesn't make sense", re.I)


def intake_sentence(purpose, time_budget, self_level) -> str:
    """The learner's intake as one sentence ("" when none was given); read by the plan writer."""
    words = [INTAKE[k][v][1] for k, v in (("purpose", purpose), ("time_budget", time_budget), ("self_level", self_level)) if v in INTAKE[k]]
    return ("About this learner (they said so themselves): " + "; ".join(words) + ".") if words else ""


def _belief(text: str) -> str:
    return re.sub(r"^(the learner\s+)?believes\s+", "", text.strip(), flags=re.I).rstrip(". ")


def facts_text(facts: dict) -> str:
    """The FACTS block as measured: one "- " line per fact. Intake only when Mindprint knows nothing about the concept."""
    tried = facts.get("tried") or []
    lines = [f"Concept level: {LEVEL_WORDS.get(facts.get('level') or 'new', 'new to the learner')}.",
             "Moves already tried on this concept: " + ("; ".join(f"{m} -> {OUTCOME_WORDS.get(o, o)}" for m, o in tried) if tried else "none") + "."]
    if facts.get("misconception"):
        lines.append(f"Open misconception: learner believes {_belief(facts['misconception'])}.")
    if facts.get("level") in (None, "new") and not tried and not facts.get("misconception"):
        for key, label in (("purpose", "Purpose"), ("time_budget", "Time available"), ("self_level", "Learner's own view of their level")):
            if facts.get(key) in INTAKE[key]:
                lines.append(f"{label}: {INTAKE[key][facts[key]][1]}.")
    return "\n".join("- " + line for line in lines)


def vetoes(facts: dict, message: str) -> set:
    """The three objective vetoes, nothing else (taste rules hurt in the measurement)."""
    tried = facts.get("tried") or []
    out = set()
    if facts.get("level") in ("understood", "remembered"):
        out |= {"explain_direct", "worked_example"}
    out |= {m for m, _ in tried if sum(1 for t, o in tried if t == m and o == "wrong") >= 2}
    last = facts.get("last_move") or (tried[-1][0] if tried else None)    # last_move: the latest move on any step (not in the prompt text)
    if last and EXPLAIN_DIFFERENTLY.search(message or ""):
        out.add(last)
    return out


def _system(ids: Iterable[str]) -> str:
    """The selector prompt as measured."""
    keep = set(ids)
    lst = "\n".join(f"- {i}: {MOVES[i][1]} (good when: {MOVES[i][2]})" for i in MOVES if i in keep)
    return ("You are an AI tutor. For the next lesson step, choose ONE teaching move from this list:\n" + lst +
            '\nReply with JSON only: {"move": "<id>", "reason": "<short reason>"}')


def choose_move(step: str, topic: str, message: str, facts: dict, chat: Callable, removed: Iterable[str] = ()) -> dict:
    """One model call over the moves that are not removed. An id outside them falls back to the first allowed of FALLBACK."""
    gone = set(removed)
    allowed = [i for i in MOVES if i not in gone]
    user = (f"Topic: {_clean_text(topic, 200)}\nStep title: {_clean_text(step, 200)}\nLearner's latest message: \"{_clean_text(message, 500)}\"\n\n"
            "FACTS (from the system):\n" + facts_text(facts))
    reply = chat(_system(allowed), user)
    reply = reply if isinstance(reply, dict) else {}
    move = str(reply.get("move") or "").strip()
    if move in allowed:
        return {"move": move, "reason": str(reply.get("reason") or "")[:300]}
    return {"move": next((i for i in FALLBACK if i in allowed), allowed[0]), "reason": "fallback: the reply was not an allowed move"}


def azure_move_chat(system: str, user: str) -> dict:
    """The measured call: the tutor's own temperature (0.7), JSON mode, short reply."""
    resp = get_azure_client().chat.completions.create(
        model=AUTHOR_DEPLOYMENT, temperature=0.7, max_tokens=300, response_format={"type": "json_object"},
        messages=[{"role": "system", "content": system}, {"role": "user", "content": user}])
    return json.loads(resp.choices[0].message.content)


def move_note(move: str) -> str:
    label, does, _ = MOVES[move]
    return f"TEACHING MOVE for this turn (chosen for this learner): {label}: {does}."
