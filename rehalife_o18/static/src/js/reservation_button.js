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
    static props = { close: Function, onSelect: Function };

    setup() {
        this.orm   = useService("orm");
        this.state = useState({
            reservations: [],
            loading: true,
            searchName:   '',
            searchBranch: '',
        });
        onMounted(() => this._load());
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

    async _load() {
        try {
            this.state.reservations = await this.orm.searchRead(
                "rehalife.reservation",
                [
                    ["invoice_status", "=", "pending"],
                    ["status",         "=", "COMPLETED"],
                ],
                [
                    "id", "partner_id", "reservation_date",
                    "reservation_time", "sub_specialty",
                    "doctor_name", "branch_name",
                ],
                { limit: 50, order: "reservation_date desc" }
            );
        } finally {
            this.state.loading = false;
        }
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
        this._pos    = usePos();
    },

    openReservations() {
        this._dialog.add(ReservationDialog, {
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
                        const loaded = await pos.data.load("res.partner", [partnerId]);
                        partner = loaded?.[0];
                    }

                    if (partner) {
                        order.set_partner(partner);   // ✅ nombre correcto Odoo 18
                        console.log("[Reservas] ✅ Partner asignado:", partner.name);
                    } else {
                        console.warn("[Reservas] Partner no encontrado:", partnerId);
                    }
                } catch (e) {
                    console.warn("[Reservas] Error cargando partner:", e);
                }

                // ── 2. Agregar línea con producto Consulta ────────────────
                try {
                    const products = await orm.searchRead(
                        "product.product",
                        [["name", "=", "Consulta"], ["active", "=", true]],
                        ["id", "list_price"],
                        { limit: 1 }
                    );

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
                        pos.models["pos.order.line"].create({
                            order_id:   order,
                            product_id: product,
                            qty:        1,
                            price_unit: products[0].list_price || 0,
                        });
                        console.log("[Reservas] ✅ Producto Consulta agregado, precio:", products[0].list_price);
                    } else {
                        console.warn("[Reservas] Producto no disponible en POS (verificar 'available_in_pos')");
                    }
                } catch (e) {
                    console.warn("[Reservas] Error agregando producto:", e);
                }

                try {
                    order._rehalife_reservation_id = res.id;
                    console.log(`[Reservas] ✅ Reserva ${res.id} vinculada a la orden`);
                } catch (e) {
                    console.warn("[Reservas] Error guardando nota:", e);
                }
            },
        });
    },
});