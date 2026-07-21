"""Transitional forwarding path for interaction state policy."""

from .interaction.state import CONTACT_OBSERVATION_STATES, PRESSURE_EVENT_STATES, TERMINAL_EVENT_STATES, compatibility_label, is_allowed_event_transition, is_contact, is_on_broken_side, is_on_original_protected_side, is_retest_contact, observation_event_state, opposite_role

__all__ = ["CONTACT_OBSERVATION_STATES", "PRESSURE_EVENT_STATES", "TERMINAL_EVENT_STATES", "compatibility_label", "is_allowed_event_transition", "is_contact", "is_on_broken_side", "is_on_original_protected_side", "is_retest_contact", "observation_event_state", "opposite_role"]
