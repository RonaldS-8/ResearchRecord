"""One candidate edge at a time, scoped to one task object and input role."""


def rule_supply(outputs, target_field):
    """Explicitly declared same-role output names; aliases remain undecided."""
    return True if target_field in outputs else None


def goat_question(source_contract, target_contract, target_field):
    return (
        f"Source contract: {source_contract}\nTarget contract: {target_contract}\n"
        f"Can a returned value of the source supply the target parameter {target_field!r}? "
        "Consider only this parameter. Other arguments may come from other sources. "
        "An argument merely accepted by the source is insufficient. Return JSON with "
        "supplies (true, false, or null when uncertain), output_field, and reason."
    )


def order_edge(supplies, field, required, valid_fields):
    """valid_fields contains only current, applicable bindings for this target."""
    if field not in required:
        raise ValueError("Expected a required target parameter")
    if field in valid_fields:
        return "already_available"
    if supplies is not True:
        return "unsupported" if supplies is False else "unknown"
    if set(required) - set(valid_fields) - {field}:
        return "partial_supply"
    return "enables_target"
