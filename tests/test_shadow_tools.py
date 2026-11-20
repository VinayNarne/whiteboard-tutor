"""The review tools of the shadow validator (scripts/shadow_report.py, scripts/shadow_review.py): pure helpers only, no logs or database needed."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))

import shadow_report as rep
import shadow_review as rev


def test_drawings_are_typed_by_their_shape_roles_and_sized_by_shape_count():
    assert rep.kind_of({"roles": {"connector": 4, "node": 3}, "shapes_new": 12}) == "connector-heavy"
    assert rep.kind_of({"roles": {"label": 9, "node": 3}, "shapes_new": 12}) == "text-heavy"
    assert rep.kind_of({"roles": {"node": 1, "label": 1}, "shapes_new": 2}) == "simple"
    assert rep.kind_of({"roles": {"node": 6, "label": 3}, "shapes_new": 9}) == "mixed"
    assert rep.kind_of({"shapes_new": 9}) == "unknown", "records written before the roles field"
    assert [rep.size_of({"shapes_new": n}) for n in (3, 10, 30)] == ["small (1-5 shapes)", "medium (6-15)", "large (16+)"]


def rec(i, existing, proposed, kind="x"):
    return {"event": "shadow_validated", "data": {"element_id": f"e{i}", "existing": existing, "proposed": proposed, "differs": existing != proposed,
                                                  "reject_kinds": {kind: 1} if proposed == "reject" else {}}}


def test_the_sample_takes_disagreements_across_categories_and_both_kinds_of_agreement():
    ok = [rec(i, "accept", "reject", "connector_through_node") for i in range(30)] + [rec(40 + i, "reject", "accept") for i in range(3)] + \
         [rec(60 + i, "accept", "reject", "label_label") for i in range(3)] + [rec(80 + i, "accept", "accept") for i in range(20)] + [rec(100 + i, "reject", "reject", "region_overlap_hides") for i in range(20)]
    dis, agree = rev.select_samples(ok, 9, 6)
    assert len(dis) == 9 and len({(r["data"]["existing"], r["data"]["proposed"], sorted(r["data"]["reject_kinds"] or {"-": 1})[0]) for r in dis}) == 3, "every category appears before one repeats"
    assert len(agree) == 6 and {r["data"]["proposed"] for r in agree} == {"accept", "reject"}
    assert rev.select_samples(ok, 9, 6)[0] == dis, "the sample is reproducible"


def test_the_overlay_draws_a_box_for_each_blamed_shape_and_ignores_text_it_cannot_read():
    out = rev.overlay([{"kind": "k", "a": "rect@10,20,110,80", "b": "text[5]@5,5,50,25"}, {"kind": "k", "a": "garbage"}], "#f00", "2")
    assert out.count("<rect") == 2 and 'x="10.0"' in out and 'width="100.0"' in out
