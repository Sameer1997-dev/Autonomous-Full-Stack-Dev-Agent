class TaskManager:
    def __init__(self, filename='task.json'):
        self.filename = filename
        self.tasks = self.load_tasks()

    def load_tasks(self):
        try:
            with open(self.filename, 'r') as file:
                return json.load(file)
        except FileNotFoundError:
            return []

    def save_tasks(self):
        with open(self.filename, 'w') as file:
            json.dump(self.tasks, file, indent=4)

    def create_task(self, task):
        self.tasks.append(task)
        self.save_tasks()

    def list_tasks(self):
        return self.tasks

    def mark_task_as_completed(self, task_id):
        for task in self.tasks:
            if task['id'] == task_id:
                task['completed'] = True
                self.save_tasks()
                return True
        return False
