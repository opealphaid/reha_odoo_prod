/** @odoo-module **/

import { Component, useState, onMounted } from "@odoo/owl";
import { useService } from "@web/core/utils/hooks";
import { Dialog } from "@web/core/dialog/dialog";
import { patch } from "@web/core/utils/patch";
import { ProductScreen } from "@point_of_sale/app/screens/product_screen/product_screen";
import { usePos } from "@point_of_sale/app/store/pos_hook";

// ── Dialog de reservas ────────────────────────────────────────────────────────
export class ReservationDialog extends Component {
    static template = "rehalife_o18.ReservationDialog";
    static components = { Dialog };
    static props = {
        close: Function,
        onSelect: Function,
        addedReservationIds: { type: Set, optional: true },
    };

    setup() {
        this.orm   = useService("orm");
        this.addedReservationIds = this.props.addedReservationIds || new Set();
        this.state = useState({
            tab: 'reservas',
            reservations: [],
            loading: true,
            facturasAseguradoras: [],
            loadingFacturas: true,
            searchName:   '',
            searchBranch: '',
        });
        onMounted(() => {
            this._load();
            this._loadFacturasAseguradoras();
        });
    }

    isAdded(res) {
        return this.addedReservationIds.has(res.id);
    }

    get filteredReservations() {
    const name   = this.state.searchName.toLowerCase().trim();
    const branch = this.state.searchBranch.toLowerCase().trim();

    return this.state.reservations.filter(res => {
        const patientName = (res.partner_id[1] || '').toLowerCase();
        const branchName  = (res.branch_name   || '').toLowerCase();

        const matchName   = !name   || patientName.includes(name);
        const matchBranch = !branch || branchName.includes(branch);

        return matchName && matchBranch;
    });
}

    get filteredFacturasAseguradoras() {
        const name = this.state.searchName.toLowerCase().trim();
        return this.state.facturasAseguradoras.filter(factura => {
            const aseguradoraName = (factura.partner_id[1] || '').toLowerCase();
            return !name || aseguradoraName.includes(name);
        });
    }

    // Etiquetas en español para account.move.state (borrador/publicada).
    moveStateLabel(value) {
        const labels = { draft: 'Borrador', posted: 'Publicada', cancel: 'Cancelada' };
        return labels[value] || value || '—';
    }

    // Etiquetas en español para account.move.payment_state (no todos los
    // valores nativos de Odoo se traducen solos en un searchRead).
    paymentStateLabel(value) {
        const labels = {
            not_paid: 'Sin Pagar',
            in_payment: 'En Proceso de Pago',
            paid: 'Pagada',
            partial: 'Pago Parcial',
            reversed: 'Revertida',
        };
        return labels[value] || value || '—';
    }

    async _load() {
        try {
            this.state.reservations = await this.orm.searchRead(
                "rehalife.reservation",
                [
                    ["invoice_status", "=", "pending"],
                    ["status",         "in", ["IN_ROOM", "IN_CONSULTATION", "COMPLETED"]],
                ],
                [
                    "id", "partner_id", "reservation_date",
                    "reservation_time", "sub_specialty",
                    "doctor_name", "branch_name",
                    "service_type_external_id", "service_type_name",
                    "modalidad", "monto_a_pagar_paciente", "monto_cobertura_seguro",
                ],
                { limit: 50, order: "reservation_date desc" }
            );
        } finally {
            this.state.loading = false;
        }
    }

    // Solo consulta y enlace al backend — la facturación se dispara al
    // aprobar cada Nota de Conformidad (una factura por NC, ver
    // rehalife.nota.conformidad.action_aprobar), no se cobra desde el POS
    // (decisión confirmada con el usuario). Se consulta account.move
    // directo (no sale.order/Pedido Marco): un Pedido Marco puede tener
    // ahora varias facturas —una por NC aprobada—, ya no una sola.
    async _loadFacturasAseguradoras() {
        try {
            this.state.facturasAseguradoras = await this.orm.searchRead(
                "account.move",
                [
                    ["move_type", "=", "out_invoice"],
                    ["state", "!=", "cancel"],
                    ["partner_id.is_aseguradora", "=", true],
                    ["payment_state", "!=", "paid"],
                ],
                [
                    "id", "name", "partner_id", "invoice_origin",
                    "amount_total", "state", "payment_state",
                ],
                { limit: 50, order: "id desc" }
            );
        } finally {
            this.state.loadingFacturas = false;
        }
    }

    openFactura(factura) {
        window.open(
            `/web#id=${factura.id}&model=account.move&view_type=form`,
            "_blank"
        );
    }

    async selectReservation(res) {
        await this.props.onSelect(res);
        this.props.close();
    }
}

// ── Parche sobre ProductScreen ────────────────────────────────────────────────
patch(ProductScreen.prototype, {
    setup() {
        super.setup();
        this._dialog = useService("dialog");
        this._orm    = useService("orm");
        this._notification = useService("notification");
        this._pos    = usePos();
    },

    openReservations() {
        const order = this._pos.selectedOrder;
        const addedReservationIds = new Set(
            (order?.lines || [])
                .map(line => line.rehalife_reservation_id?.id ?? line.rehalife_reservation_id)
                .filter(Boolean)
        );

        this._dialog.add(ReservationDialog, {
            addedReservationIds,
            onSelect: async (res) => {
                const pos = this._pos;
                const orm = this._orm;
                const order = pos.selectedOrder;

                if (!order) {
                    console.warn("[Reservas] No hay orden activa");
                    return;
                }

                // ── 1. Asignar partner ────────────────────────────────────
                try {
                    const partnerId = Array.isArray(res.partner_id)
                        ? res.partner_id[0]
                        : res.partner_id;

                    let partner = pos.models["res.partner"]?.getBy("id", partnerId);

                    if (!partner) {
                        // pos.data.load(...) no existe en esta versión de
                        // point_of_sale (el servicio `data`/PosData no expone
                        // `load`) — se reemplaza por `orm.read` (mismo
                        // servicio ya usado más abajo para product.product)
                        // y se registra el resultado en el store reactivo del
                        // POS con `.create()`, igual patrón que
                        // pos.models["pos.order.line"].create(...) más abajo.
                        const [partnerData] = await this._orm.read("res.partner", [partnerId], []);
                        if (partnerData) {
                            partner = pos.models["res.partner"].create(partnerData);
                        }
                    }

                    if (partner) {
                        order.set_partner(partner);   // ✅ nombre correcto Odoo 18
                        console.log("[Reservas] ✅ Partner asignado:", partner.name);
                    } else {
                        const msg = `No se encontró el paciente (partner ${partnerId}) para asignarlo a la orden. Verifique manualmente el cliente antes de cobrar.`;
                        console.warn("[Reservas]", msg);
                        this._notification.add(msg, { type: "danger", sticky: true });
                    }
                } catch (e) {
                    const msg = `No se pudo asignar el paciente a la orden (${e?.message || e}). Verifique manualmente el cliente antes de cobrar.`;
                    console.warn("[Reservas] Error cargando partner:", e);
                    this._notification.add(msg, { type: "danger", sticky: true });
                }

                // ── 2. Agregar línea con el producto del servicio real ────
                try {
                    let products = [];

                    if (res.service_type_external_id) {
                        products = await orm.searchRead(
                            "product.product",
                            [
                                ["product_tmpl_id.rehalife_external_id", "=", res.service_type_external_id],
                                ["product_tmpl_id.available_in_pos", "=", true],
                                ["active", "=", true],
                            ],
                            ["id", "list_price"],
                            { limit: 1 }
                        );
                        if (!products.length) {
                            console.warn(
                                "[Reservas] Servicio aún no homologado/activo en POS, usando fallback 'Consulta':",
                                res.service_type_name || res.service_type_external_id
                            );
                        }
                    }

                    if (!products.length) {
                        products = await orm.searchRead(
                            "product.product",
                            [["name", "=", "Consulta"], ["active", "=", true]],
                            ["id", "list_price"],
                            { limit: 1 }
                        );
                    }

                    if (!products.length) {
                        console.warn("[Reservas] Producto Consulta no encontrado en DB");
                        return;
                    }

                    const productId = products[0].id;
                    let product = pos.models["product.product"]?.getBy("id", productId);

                    if (!product) {
                        const loaded = await pos.data.load("product.product", [productId]);
                        product = loaded?.[0];
                    }

                    if (product) {
                        const patientName = Array.isArray(res.partner_id)
                            ? res.partner_id[1]
                            : "";

                        // Modalidad Seguro (HU-12): el paciente solo paga su
                        // parte — precio del servicio menos lo que cubre la
                        // aseguradora, calculado en Odoo (NO en el frontend)
                        // a partir de la Nota de Conformidad de la reserva
                        // (rehalife.reservation._compute_cobertura_seguro).
                        // El monto que cubre la aseguradora NO se cobra en
                        // esta orden de POS — se factura aparte, al
                        // aprobarse esa Nota de Conformidad.
                        const esSeguro = res.modalidad === "seguro";
                        const priceUnit = esSeguro
                            ? res.monto_a_pagar_paciente
                            : (products[0].list_price || 0);
                        let nombreLinea = `Reserva — ${res.sub_specialty || "General"} (${patientName})`;
                        if (esSeguro) {
                            nombreLinea += ` — Seguro cubre ${res.monto_cobertura_seguro.toFixed(2)} Bs.`;
                            if (!res.monto_cobertura_seguro) {
                                nombreLinea += " ⚠️ SIN NOTA DE CONFORMIDAD TODAVÍA — verificar el Pedido de Venta Marco de la reserva";
                                console.warn(
                                    "[Reservas] Sin Nota de Conformidad (o sin monto configurado en su línea " +
                                    "del Pedido de Venta Marco) para esta reserva — cobrando el precio " +
                                    "completo al paciente. Reserva:", res.id
                                );
                            }
                        }

                        pos.models["pos.order.line"].create({
                            order_id:   order,
                            product_id: product,
                            qty:        1,
                            price_unit: priceUnit,
                            rehalife_reservation_id: res.id,
                            full_product_name: nombreLinea,
                        });
                        console.log("[Reservas] ✅ Producto agregado, precio:", priceUnit);
                        console.log(`[Reservas] ✅ Reserva ${res.id} vinculada a la línea`);
                    } else {
                        console.warn("[Reservas] Producto no disponible en POS (verificar 'available_in_pos')");
                    }
                } catch (e) {
                    console.warn("[Reservas] Error agregando producto:", e);
                }
            },
        });
    },
});