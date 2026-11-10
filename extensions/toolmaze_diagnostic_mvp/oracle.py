"""Separate, explicitly privileged informed reference. Never a normal policy."""


def choose_informed(private_mode, public_view):
    if private_mode not in ('P1','P2'):
        raise ValueError('Outside scope')
    return 'retry' if private_mode=='P1' and public_view['costs']['retry_if_recovers']<public_view['costs']['switch'] else 'switch'
