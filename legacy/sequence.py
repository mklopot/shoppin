import yaml


class Sequence:
    def __init__(self) -> None:
        self.data = []
        self.last_updated = None

    def add(self, item: str) -> None:
        item = item.lower()
        if item not in self. data:
            self.data.insert(0, item)

    def update(self, item: str) -> None:
        item = item.lower()
        if item == self.last_updated:
            return
        if item not in self.data:
            self.add(item)
            self.last_updated = item
            return

        self.data.remove(item)
        if self.last_updated:
            self.data.insert(self.data.index(self.last_updated)+1, item)
        else:
            self.data.insert(0, item)
        self.last_updated = item

    def get_sequence(self) -> None:
        return self.data

    def reset_pointer(self) -> None:
        self.last_updated = None
    
    def save(self, filename="sequence-default.yaml"):
        with open(filename, 'w') as f:
            yaml.dump((self.data, self.last_updated), f)

    def load(self, filename="sequence-default.yaml"):
        try:
            with open(filename) as f:
                self.data, self.last_updated = yaml.load(f)
                return True
        except TypeError:
            pass
            return False

