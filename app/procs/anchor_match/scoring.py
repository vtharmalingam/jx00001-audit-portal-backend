
# Deterministic scoring logic
def compute_alignment(matches):
    """
    matches: list of dicts with keys:
      - similarity
      - weight
    """
    raw_score = 0.0
    max_possible = 0.0

    for m in matches:
        raw_score += m["similarity"] * m["weight"]
        max_possible += abs(m["weight"])

    if max_possible == 0:
        return 0

    normalized = max(raw_score / max_possible, 0)
    return round(normalized * 100, 2)
