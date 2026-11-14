"""Shared Keyword metadata for guided and generic parameter editors."""
from collections.abc import Mapping


def keyword_allows_unset(option, value_type):
    """Offer unset only for optional scalar keywords without an effective default."""
    if option is None or option._definition.type is not value_type:
        # An optional array is not the same as an optional element of it.
        return False
    optional = option._definition.is_optional
    return bool(optional(option) if callable(optional) else optional) and option.default_value is None


def choice_description(description):
    if isinstance(description, (tuple, list)):
        return ": ".join(str(part) for part in description)
    return str(description) if description is not None else ""


def keyword_items(option=None, *, value_type=None, index=None, atoms=None):
    """Use atom-specific choices when available, otherwise the type's choices.

    An empty provider result means no predefined choices for these atoms;
    it must not fall back to the unfiltered list. Without atoms, use the type.
    """
    if value_type is None:
        value_type = option._definition.type
        if index is not None:
            value_type = value_type.type
    provider = getattr(option, "choices_for_atoms", None)
    if provider is None and option is not None:
        provider = getattr(option._definition, "choices_for_atoms", None)
    choices = provider(atoms) if callable(provider) and atoms is not None else value_type.items()
    if isinstance(choices, Mapping):
        choices = choices.items()
    if keyword_allows_unset(option, value_type):
        yield None, "Custom path" if option.name == "KPATH" else "Not set"
    for value, description in choices:
        if value is not None:
            yield value_type.convert(value), choice_description(description)


def keyword_current_value(option, value_type, value):
    if keyword_allows_unset(option, value_type) and not option.is_set():
        return None
    return value
