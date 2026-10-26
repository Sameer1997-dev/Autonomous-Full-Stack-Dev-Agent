from tests.task_manager import TaskManager

if __name__ == '__main__':
    task_manager = TaskManager()
    task_manager.create_task({'id': 1, 'description': 'Test task'})
    print(task_manager.list_tasks())
