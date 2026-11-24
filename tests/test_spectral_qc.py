from itertools import combinations

import numpy as np
import pytest

from soil_mir.qc import (
    Criteria, align_group, classify_pair, diagnose, group_filenames,
    group_issues, mad_threshold, pair_metrics, parse_filename,
)


def scans():
    return [parse_filename(f"NSSH_2_{i}_A{i+6}.0", "NSSH") for i in range(1, 4)]


def test_filename_grouping():
    names = ["NSSH_01_1_A9.0", "NSSH_01_2_A10.0", "NSSH_01_3_A11.1", "unknown.0"]
    groups, unmatched, pattern = group_filenames(names)
    assert pattern == "NSSH"
    assert [s.replicate for s in groups["NSSH_01"]] == [1, 2, 3]
    assert unmatched == ["unknown.0"]
    assert not any(group_issues(groups["NSSH_01"]).values())
    extra = parse_filename("NSSH_01_1_A9.1", "NSSH")
    assert group_issues(groups["NSSH_01"] + [extra])["duplicate"] == [1]


@pytest.mark.parametrize("statuses,expected,suspect", [
    (["Pass", "Pass", "Pass"], "Pass", None),
    (["Pass", "Fail", "Fail"], "Review", 3),
    (["Fail", "Pass", "Fail"], "Review", 2),
    (["Fail", "Fail", "Pass"], "Review", 1),
    (["Pass", "Review", "Fail"], "Review", 3),
    (["Pass", "Pass", "Fail"], "Review", None),
    (["Fail", "Fail", "Fail"], "Fail", None),
    (["Review", "Fail", "Fail"], "Review", None),
    (["Pass", "Invalid", "Fail"], "Incomplete", None),
])
def test_triangle(statuses, expected, suspect):
    ss = scans()
    edges = [(a.filename, b.filename, status)
             for (a, b), status in zip(combinations(ss, 2), statuses)]
    result = diagnose(ss[::-1], edges)
    assert result["status"] == expected
    assert result["suspected_replicate"] == suspect
    if suspect:
        assert result["suspected_file"] == ss[suspect-1].filename
    if statuses.count("Pass") == 2:
        assert set(result["review_candidates"]) == {ss[1].filename, ss[2].filename}


def test_threshold_and_advanced():
    metric = {"r": .996, "nrmse": 2.}
    assert classify_pair(metric, Criteria())[0] == "Fail"
    assert classify_pair(metric, Criteria(similarity=99.3))[0] == "Pass"
    for nrmse, result in [(2, "Pass"), (5, "Review"), (5.01, "Fail")]:
        assert classify_pair({"r": .999, "nrmse": nrmse},
                             Criteria(advanced=True))[0] == result


def test_metrics():
    axis = np.linspace(600, 4000, 341)
    x = 1 + np.sin(axis / 100)
    y = x + .2
    m = pair_metrics(x, y, axis)
    assert m["r"] == pytest.approx(1)
    assert m["rmse"] == pytest.approx(.2)
    assert m["mean_difference"] == pytest.approx(-.2)
    rev = pair_metrics(y, x, axis)
    assert m["nrmse"] == pytest.approx(rev["nrmse"])
    assert m["sam"] == pytest.approx(rev["sam"])
    assert pair_metrics(x, 2*x, axis)["sam"] == pytest.approx(0, abs=2e-6)
    with pytest.raises(ValueError, match="Constant"):
        pair_metrics(np.ones_like(x), y, axis)


def test_alignment_and_co2():
    axis = np.linspace(600, 4000, 341)
    x = np.sin(axis/100)
    grid, aligned = align_group({"a": (x, axis), "b": (x[::-1], axis[::-1])})
    assert np.array_equal(grid, axis)
    assert np.array_equal(aligned["a"], aligned["b"])
    with pytest.raises(ValueError, match="covered"):
        align_group({"a": (x[1:], axis[1:])})
    y = x.copy()
    y[(axis >= 2300) & (axis <= 2400)] += .2
    result = pair_metrics(x, y, axis, exclude_co2=True)
    assert result["rmse"] == 0
    assert result["regional"][(2300, 2400)] == pytest.approx(.2)


def test_incomplete_and_mad():
    ss = scans()[:2]
    edges = [(ss[0].filename, ss[1].filename, "Pass")]
    assert diagnose(ss, edges)["status"] == "Incomplete"
    assert diagnose(ss, edges, expected=2)["status"] == "Pass"
    assert mad_threshold([1] * 30) is None
    assert mad_threshold([1, 2]) is None
    assert mad_threshold(list(range(30))) > 14.5
