import nol_monitor


def test_second_acquire_on_same_path_returns_none(tmp_path):
    lock_path = str(tmp_path / ".nol_monitor.lock")

    first = nol_monitor.acquire_single_instance_lock(lock_path)
    assert first is not None

    second = nol_monitor.acquire_single_instance_lock(lock_path)
    assert second is None  # 이미 잠겨 있으면 None

    first.close()

    # 해제 후에는 다시 획득 가능해야 한다
    third = nol_monitor.acquire_single_instance_lock(lock_path)
    assert third is not None
    third.close()
