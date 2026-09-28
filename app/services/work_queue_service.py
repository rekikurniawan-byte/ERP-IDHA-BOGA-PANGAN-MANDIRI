"""Antrean kerja harian OWNER/ADMIN: angka di grup menu "Antrean Kerja".

Perapian menu 2026-09-28 (permintaan owner: sistem harus rapi, tidak perlu
mencari-cari). Pekerjaan yang menunggu tindakan -- pesanan portal, bukti bayar,
uang muka yang harus dikembalikan, persetujuan -- dulu tersebar di halaman lain
dan tidak ada di menu. Hanya membaca.
"""
from app.models.system import ApprovalRequest, DigitalAttachment, PortalOrderDraft

# Bukti bayar yang masih menunggu Finance: belum diperiksa, atau sudah
# diverifikasi tapi nominalnya belum dicatat.
WAITING_PROOF_TYPES = ("PAYMENT_PROOF_PENDING", "PAYMENT_PROOF_VERIFIED")


def work_queue_counts(branch_id):
    from app.services.prepaid_order_service import advances_to_refund

    counts = {
        "portal_orders": PortalOrderDraft.query.filter(
            PortalOrderDraft.branch_id == branch_id,
            PortalOrderDraft.status == "PENDING_ADMIN_CONFIRMATION",
        ).count(),
        "payment_proofs": DigitalAttachment.query.filter(
            DigitalAttachment.branch_id == branch_id,
            DigitalAttachment.module == "PORTAL_PAYMENT",
            DigitalAttachment.attachment_type.in_(WAITING_PROOF_TYPES),
            DigitalAttachment.is_deleted.is_(False),
        ).count(),
        "refunds": len(advances_to_refund(branch_id)),
        "approvals": ApprovalRequest.query.filter(
            ApprovalRequest.branch_id == branch_id,
            ApprovalRequest.status == "SUBMITTED",
        ).count(),
    }
    counts["total"] = sum(counts.values())
    return counts
