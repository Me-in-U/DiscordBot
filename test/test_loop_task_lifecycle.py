import unittest
from pathlib import Path


LOOP_TASK_LIFECYCLE_PATH = Path("util/loop/task_lifecycle.py")
LEGACY_LOOP_TASK_LIFECYCLE_PATH = Path("util/loop_task_lifecycle.py")


class FakeLoopTask:
    def __init__(self, running: bool = False):
        self.running = running
        self.started = 0
        self.cancelled = 0

    def is_running(self) -> bool:
        return self.running

    def start(self) -> None:
        self.started += 1
        self.running = True

    def cancel(self) -> None:
        self.cancelled += 1
        self.running = False


class Owner:
    def __init__(self):
        self.ready_task = FakeLoopTask()
        self.running_task = FakeLoopTask(running=True)


class LoopTaskLifecycleTests(unittest.TestCase):
    def test_loop_task_lifecycle_lives_under_loop_package(self):
        self.assertTrue(LOOP_TASK_LIFECYCLE_PATH.exists())
        self.assertFalse(LEGACY_LOOP_TASK_LIFECYCLE_PATH.exists())

    def test_start_loop_tasks_starts_only_stopped_tasks(self):
        from util.loop.task_lifecycle import start_loop_tasks

        owner = Owner()
        start_loop_tasks(owner, ("ready_task", "running_task"))

        self.assertEqual(owner.ready_task.started, 1)
        self.assertTrue(owner.ready_task.is_running())
        self.assertEqual(owner.running_task.started, 0)

    def test_cancel_loop_tasks_cancels_only_running_tasks(self):
        from util.loop.task_lifecycle import cancel_loop_tasks

        owner = Owner()
        cancel_loop_tasks(owner, ("ready_task", "running_task"))

        self.assertEqual(owner.ready_task.cancelled, 0)
        self.assertEqual(owner.running_task.cancelled, 1)
        self.assertFalse(owner.running_task.is_running())

    def test_missing_task_name_raises_clear_attribute_error(self):
        from util.loop.task_lifecycle import start_loop_tasks

        owner = Owner()
        with self.assertRaisesRegex(AttributeError, "missing_task"):
            start_loop_tasks(owner, ("missing_task",))


if __name__ == "__main__":
    unittest.main()
