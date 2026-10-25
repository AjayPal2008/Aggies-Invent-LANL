from backend.lesson_sections import lesson_sections


def test_lesson_expansion_preserves_sources_and_concept_links():
    point = {"id": "kp1", "point": "Computer security and vulnerabilities", "explanation": "A computer vulnerability is a weakness in a system. Security controls protect information from threats."}
    related = {"id": "kp2", "point": "Security controls", "explanation": "Computer security controls protect information and reduce the threats associated with system vulnerabilities."}
    context = "Computer security uses several layers of controls to protect system information from vulnerabilities and threats. These controls include preventive and detective techniques that support security objectives. Understanding system vulnerabilities helps explain how these different information security controls complement one another."
    resource = {"data": {"key_points": [point, related], "terms": [{"term": "Vulnerability", "definition": "A system weakness."}]}, "raw": context}
    sections = lesson_sections(resource, [point], "Understand vulnerabilities")
    assert len(sections) >= 4
    assert sections[0]["explanation"] == point["explanation"]
    assert all(s["concept_id"] == "kp1" for s in sections)
    assert any(s["explanation"] == context for s in sections)
    assert any(s["kind"] == "Glossary" for s in sections)
    assert all(" ".join(s["paragraphs"]) == s["explanation"] for s in sections)


def test_empty_topic_does_not_invent_a_lesson():
    assert lesson_sections({"data": {"key_points": []}, "raw": ""}, []) == []
