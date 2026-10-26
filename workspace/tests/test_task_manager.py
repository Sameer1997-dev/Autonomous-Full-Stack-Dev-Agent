import pytest
from task_manager import TaskManager

@pytest.fixture
def task_manager():
    tm = TaskManager()
    yield tm
    tm.save_tasks()

def test_create_task(task_manager):
    task_manager.create_task({'description': 'Test task', 'completed': False})
    assert len(task_manager.tasks) == 1

def test_list_tasks(task_manager):
    task_manager.create_task({'description': 'Test task', 'completed': False})
    tasks = task_manager.list_tasks()
    assert len(tasks) == 1

def test_mark_task_as_completed(task_manager):
    task_manager.create_task({'description': 'Test task', 'completed': False})
    task_manager.mark_task_as_completed(1)
    tasks = task_manager.list_tasks()
    assert tasks[0]['completed'] == True
