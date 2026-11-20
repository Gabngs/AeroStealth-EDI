from dataclasses import dataclass


@dataclass
class Detection:
    cls: int
    conf: float
    x1: float
    y1: float
    x2: float
    y2: float

    def to_box(self) -> dict:
        return {"cls": self.cls, "conf": self.conf,
                "xyxy": [self.x1, self.y1, self.x2, self.y2], "src": "model"}
