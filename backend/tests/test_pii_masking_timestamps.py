"""Test that mask_dialogue preserves start_offset/end_offset."""
import sys
sys.path.insert(0, r'<backend>')
sys.path.insert(0, r'<transcrib>')

from app.models import ParsedDialog, DialogueTurn
from app.services.pii_masking import PIIMaskingService


def test_mask_dialogue_preserves_timestamps():
    """Regression test for bug: masked_turn was missing start_offset/end_offset."""
    svc = PIIMaskingService()
    if not svc.is_available():
        import pytest
        pytest.skip('PII masking service not available')

    turns = [
        DialogueTurn(
            turn_index=0, speaker='Клиент',
            text='Меня зовут Иван Иванович',
            start_offset=10.0, end_offset=20.0,
        ),
        DialogueTurn(
            turn_index=1, speaker='Сотрудник',
            text='Здравствуйте, чем могу помочь',
            start_offset=20.0, end_offset=25.0,
        ),
    ]
    dialog = ParsedDialog(
        filename='test.rtf',
        turns=turns,
        total_turns=2,
        client_turns=1,
        employee_turns=1,
    )

    result = svc.mask_dialogue(dialog)
    assert result.error is None, f'mask_dialogue failed: {result.error}'
    assert result.masked_dialogue is not None

    masked_turns = result.masked_dialogue.turns
    assert len(masked_turns) == 2

    for orig, masked in zip(turns, masked_turns):
        assert masked.start_offset == orig.start_offset, \
            f'turn {masked.turn_index}: start_offset lost! ' \
            f'expected={orig.start_offset}, got={masked.start_offset}'
        assert masked.end_offset == orig.end_offset, \
            f'turn {masked.turn_index}: end_offset lost! ' \
            f'expected={orig.end_offset}, got={masked.end_offset}'
        assert masked.turn_index == orig.turn_index
        assert masked.speaker == orig.speaker
