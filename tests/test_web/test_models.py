# SPDX-License-Identifier: GPL-3.0-or-later
import pytest

from iib.exceptions import ValidationError
from iib.web import models


def test_request_add_architecture(db, minimal_request):
    minimal_request.add_architecture('amd64')
    minimal_request.add_architecture('s390x')
    db.session.commit()
    assert len(minimal_request.architectures) == 2
    assert minimal_request.architectures[0].name == 'amd64'
    assert minimal_request.architectures[1].name == 's390x'

    # Verify that the method is idempotent
    minimal_request.add_architecture('amd64')
    db.session.commit()
    assert len(minimal_request.architectures) == 2


def test_request_add_state(db, minimal_request):
    minimal_request.add_state('in_progress', 'Starting things up')
    minimal_request.add_state('complete', 'All done!')
    db.session.commit()

    assert len(minimal_request.states) == 2
    assert minimal_request.state.state_name == 'complete'
    assert minimal_request.state.state_reason == 'All done!'
    assert minimal_request.states[0].state_name == 'in_progress'
    # Ensure that minimal_request.state is the latest state
    assert minimal_request.state == minimal_request.states[1]


def test_request_add_state_invalid_state(db, minimal_request):
    with pytest.raises(ValidationError, match='The state "invalid" is invalid'):
        minimal_request.add_state('invalid', 'Starting things up')


@pytest.mark.parametrize('state', ('complete', 'failed'))
def test_request_add_state_already_done(state, db, minimal_request):
    with pytest.raises(ValidationError, match=f'A {state} request cannot change states'):
        minimal_request.add_state(state, 'Done')
        db.session.commit()
        minimal_request.add_state('in_progress', 'Oops!')


def test_get_state_names():
    assert models.RequestStateMapping.get_names() == ['complete', 'failed', 'in_progress']


def test_get_type_names():
    assert models.RequestTypeMapping.get_names() == ['add', 'generic', 'regenerate_bundle', 'rm']


@pytest.mark.parametrize(
    'type_num, is_valid',
    [(0, True), (1, True), (2, True), (3, True), (5, False), ('1', False), (None, False)],
)
def test_request_type_validation(type_num, is_valid):
    if is_valid:
        models.Request(type=type_num)
    else:
        with pytest.raises(ValidationError, match=f'{type_num} is not a valid request type number'):
            models.Request(type=type_num)
