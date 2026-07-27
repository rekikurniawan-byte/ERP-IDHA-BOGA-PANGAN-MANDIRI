from datetime import datetime
from app.extensions import db
from sqlalchemy.orm import declared_attr


class BaseModel(db.Model):
    __abstract__ = True

    id = db.Column(db.Integer, primary_key=True)
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    version_id = db.Column(db.Integer, nullable=False, default=1, server_default="1")

    @declared_attr.directive
    def __mapper_args__(cls):
        return {"version_id_col": cls.version_id}
