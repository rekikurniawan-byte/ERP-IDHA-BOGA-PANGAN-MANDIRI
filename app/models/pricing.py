"""Harga jual per porsi, dengan riwayat dan tanggal berlaku.

Keputusan owner 2026-09-27: harga mengikuti harga bahan pokok dan BBM, jadi
harus bisa diubah kapan saja. Setiap perubahan adalah baris baru dengan
tanggal "berlaku mulai" -- baris lama tidak pernah diubah, supaya riwayatnya
utuh dan harga bisa dijadwalkan (naik mulai Senin depan).

- client_id kosong  = harga standar cabang (pelanggan umum, client tanpa harga khusus);
- client_id terisi  = harga kontrak client itu; menang atas harga standar.

Harga yang terpakai dikunci ke order saat order dibuat
(daily_order_details.price_per_portion), jadi perubahan harga tidak pernah
mengubah order, invoice, atau uang muka yang sudah ada.
"""
from datetime import datetime

from app.extensions import db
from app.models.base import BaseModel


class PortionPrice(BaseModel):
    __tablename__ = "portion_prices"
    __table_args__ = (
        db.CheckConstraint("price_per_portion > 0", name="ck_portion_prices_positive"),
        db.Index("ix_portion_prices_lookup", "branch_id", "client_id", "effective_from"),
    )

    branch_id = db.Column(db.Integer, db.ForeignKey("branches.id"), nullable=False)
    client_id = db.Column(db.Integer, db.ForeignKey("clients.id"), nullable=True)
    price_per_portion = db.Column(db.Numeric(18, 2), nullable=False)
    effective_from = db.Column(db.Date, nullable=False)
    notes = db.Column(db.Text, nullable=True)
    created_by = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)

    client = db.relationship("Client", foreign_keys=[client_id], lazy="joined")
    creator = db.relationship("User", foreign_keys=[created_by], lazy="joined")

    @property
    def created_at_label(self):
        value = self.created_at or datetime.utcnow()
        return value.strftime("%d-%m-%Y %H:%M")
