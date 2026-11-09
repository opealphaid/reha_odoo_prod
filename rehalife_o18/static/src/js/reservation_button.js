/** @odoo-module **/

// Diálogo "Reservas" del POS — Pagos anticipados, Fase 3.
//
// Centrado en el paciente: muestra TODAS sus reservas activas (también
// PENDING: se puede pagar por adelantado), agrupadas por servicio, y permite
// elegir cuáles cobrar (checkbox o "pagar N"). Las seleccionadas se agregan
// como UNA línea por (producto, precio) con qty = cantidad de reservas.
//
// Reglas (ver CLAUDE.MD / plan-pagos-anticipados-reservas.md):
// - El vínculo línea → reservas viaja SIEMPRE por
//   rehalife_reservation_ids_json (el Many2one no llega al servidor).
// - El precio lo decide el servidor (get_pos_charge_info): particular =
//   precio de lista; seguro = copago del paciente. Nada se calcula aquí.
// - La verificación final antes de cobrar está en
//   reservation_payment_check.js y en el servidor (pos.order.line).

import { Component, useState, onMounted } from "@odoo/owl";
import { useService } from "@web/core/utils/hooks";
import { Dialog } from "@web/core/dialog/dialog";
import { patch } from "@web/core/utils/patch";
import { ProductScreen } from "@point_of_sale/app/screens/product_screen/product_screen";
import { usePos } from "@point_of_sale/app/store/pos_hook";
import { lineReservationIds } from "@rehalife_o18/js/reservation_payment_check";

const RESERVATION_FIELDS = [
    "id", "partner_id", "reservation_date", "reservation_time", "end_time",
    "status", "sub_specialty", "doctor_name", "branch_name", "environment_name",
    "service_type_external_id", "service_type_name",
    "invoice_status", "pos_paid_amount", "paid_amount", "pos_order_id",
];

const STATUS_LABELS = {
    PENDING: "Pendiente",
    IN_ROOM: "En Sala",
    IN_CONSULTATION: "En Consulta",
    COMPLETED: "Completada",
};

const INVOICE_STATUS_LABELS = {
    invoiced: "Facturada",
    cancelled: "Cancelada",
};

function sortKey(res) {
    return `${res.reservation_date || "9999-99-99"} ${res.reservation_time || "99:99"} ${String(res.id).padStart(10, "0")}`;
}

export function formatDate(value) {
    if (!value) {
        return "—";
    }
    const [y, m, d] = String(value).split("-");
    return d && m && y ? `${d}/${m}/${y}` : String(value);
}

function money(value) {
    return (Number(value) || 0).toFixed(2);
}

// ── Dialog de reservas ────────────────────────────────────────────────────────
export class ReservationDialog extends Component {
    static template = "rehalife_o18.ReservationDialog";
    static components = { Dialog };
    static props = {
        close: Function,
        onAdd: Function,
        addedReservationIds: { type: Set, optional: true },
        // Paciente de la orden: {id, name}. Sin paciente: no se pasa.
        partner: { type: Object, optional: true },
        // La orden ya tiene líneas de reservas: no se puede cambiar de paciente.
        partnerLocked: { type: Boolean, optional: true },
    };

    setup() {
        this.orm = useService("orm");
        this.addedReservationIds = this.props.addedReservationIds || new Set();
        this.state = useState({
            partner: this.props.partner || null,
            searchQuery: "",
            searchResults: [],
            searching: false,
            reservations: [],
            // {reservation_id: info} de get_pos_charge_info. null = no se pudo
            // obtener: nada es seleccionable.
            charge: null,
            selected: {},
            payN: {},
            loading: false,
            adding: false,
            error: "",
            branchInfo: { restricted: false, branch_id: false, branch_name: "" },
        });
        onMounted(async () => {
            await this._loadBranchInfo();
            if (this.state.partner) {
                await this._loadReservations();
            }
        });
    }

    // ── Sucursal ─────────────────────────────────────────────────────────────
    get noBranchAssigned() {
        return this.state.branchInfo.restricted && !this.state.branchInfo.branch_id;
    }

    async _loadBranchInfo() {
        try {
            this.state.branchInfo = await this.orm.call(
                "rehalife.reservation", "get_pos_branch_info", []
            );
        } catch (e) {
            // La regla de registro sigue filtrando las reservas en el servidor.
            console.warn("[Reservas] No se pudo obtener la sucursal del usuario:", e);
        }
    }

    // ── Paciente ─────────────────────────────────────────────────────────────
    async searchPatients() {
        const query = this.state.searchQuery.trim();
        if (query.length < 2) {
            this.state.searchResults = [];
            return;
        }
        this.state.searching = true;
        try {
            this.state.searchResults = await this.orm.searchRead(
                "res.partner",
                [
                    ["es_paciente", "=", true],
                    "|", ["name", "ilike", query], ["vat", "ilike", query],
                ],
                ["id", "name", "vat"],
                { limit: 20, order: "name" }
            );
        } catch (e) {
            console.warn("[Reservas] Error buscando pacientes:", e);
            this.state.searchResults = [];
        } finally {
            this.state.searching = false;
        }
    }

    onSearchKeydown(ev) {
        if (ev.key === "Enter") {
            this.searchPatients();
        }
    }

    async choosePatient(partner) {
        this.state.partner = { id: partner.id, name: partner.name };
        this.state.searchResults = [];
        this.state.searchQuery = "";
        await this._loadReservations();
    }

    changePatient() {
        if (this.props.partnerLocked) {
            return;
        }
        this.state.partner = null;
        this.state.reservations = [];
        this.state.charge = null;
        this.state.selected = {};
        this.state.payN = {};
        this.state.error = "";
    }

    // ── Reservas del paciente ────────────────────────────────────────────────
    async _loadReservations() {
        if (!this.state.partner || this.noBranchAssigned) {
            return;
        }
        this.state.loading = true;
        this.state.error = "";
        this.state.selected = {};
        this.state.payN = {};
        try {
            // Todas las activas del paciente (incluye PENDING), sin límite.
            // La regla de registro de sucursal sigue aplicando en el servidor.
            const reservations = await this.orm.searchRead(
                "rehalife.reservation",
                [
                    ["partner_id", "=", this.state.partner.id],
                    ["status", "not in", ["CANCELLED", "NO_SHOW"]],
                ],
                RESERVATION_FIELDS,
                { order: "reservation_date asc, reservation_time asc, id asc" }
            );
            this.state.reservations = reservations.sort((a, b) =>
                sortKey(a).localeCompare(sortKey(b))
            );
            const pendingIds = reservations
                .filter((res) => res.invoice_status === "pending")
                .map((res) => res.id);
            this.state.charge = pendingIds.length
                ? await this.orm.call("rehalife.reservation", "get_pos_charge_info", [pendingIds])
                : {};
        } catch (e) {
            console.warn("[Reservas] Error cargando las reservas del paciente:", e);
            this.state.error = `No se pudieron cargar las reservas (${e?.message || e}).`;
            this.state.charge = null;
        } finally {
            this.state.loading = false;
        }
    }

    chargeInfo(res) {
        return this.state.charge ? this.state.charge[res.id] || null : null;
    }

    /** {selectable, label, cls, detail} de una reserva. */
    rowState(res) {
        if (res.invoice_status === "paid") {
            const amount = res.pos_paid_amount || res.paid_amount;
            return {
                selectable: false,
                label: "Pagada",
                cls: "badge bg-success",
                detail: amount ? `${money(amount)} Bs.` : "",
            };
        }
        if (res.invoice_status !== "pending") {
            return {
                selectable: false,
                label: INVOICE_STATUS_LABELS[res.invoice_status] || res.invoice_status,
                cls: "badge bg-secondary",
                detail: "",
            };
        }
        if (this.addedReservationIds.has(res.id)) {
            return { selectable: false, label: "Ya en la venta", cls: "badge bg-info text-dark", detail: "" };
        }
        const info = this.chargeInfo(res);
        if (!info) {
            return {
                selectable: false,
                label: "Sin datos de cobro",
                cls: "badge bg-warning text-dark",
                detail: "No se pudo consultar el servidor.",
            };
        }
        if (!info.chargeable) {
            return {
                selectable: false,
                label: "No cobrable",
                cls: "badge bg-danger",
                detail: info.reason || info.message || "",
            };
        }
        return { selectable: true, label: "Pendiente de pago", cls: "badge bg-light text-dark border", detail: "" };
    }

    statusLabel(res) {
        return STATUS_LABELS[res.status] || res.status || "—";
    }

    formatDate(value) {
        return formatDate(value);
    }

    money(value) {
        return money(value);
    }

    get groups() {
        const groups = new Map();
        for (const res of this.state.reservations) {
            const key = res.service_type_external_id || res.service_type_name || "sin-servicio";
            if (!groups.has(key)) {
                groups.set(key, {
                    key,
                    name: res.service_type_name || "(sin servicio)",
                    reservations: [],
                    total: 0,
                    paid: 0,
                    pending: 0,
                    selectable: [],
                });
            }
            const group = groups.get(key);
            group.reservations.push(res);
            group.total += 1;
            if (res.invoice_status === "paid") {
                group.paid += 1;
            } else if (res.invoice_status === "pending") {
                group.pending += 1;
            }
            if (this.rowState(res).selectable) {
                group.selectable.push(res);
            }
        }
        return [...groups.values()];
    }

    isSelected(res) {
        return Boolean(this.state.selected[res.id]);
    }

    toggle(res) {
        if (!this.rowState(res).selectable) {
            return;
        }
        this.state.selected[res.id] = !this.state.selected[res.id];
    }

    /** "Pagar N": selecciona las N más próximas por fecha del grupo. */
    selectFirstN(group) {
        const n = Math.max(0, Math.floor(Number(this.state.payN[group.key]) || 0));
        group.selectable.forEach((res, index) => {
            this.state.selected[res.id] = index < n;
        });
    }

    selectedCount(group) {
        return group.selectable.filter((res) => this.isSelected(res)).length;
    }

    get selectedReservations() {
        return this.state.reservations.filter(
            (res) => this.isSelected(res) && this.rowState(res).selectable
        );
    }

    get selectedTotal() {
        return this.selectedReservations.reduce(
            (sum, res) => sum + (this.chargeInfo(res)?.price_unit || 0), 0
        );
    }

    async confirm() {
        const reservations = this.selectedReservations;
        if (!reservations.length || this.state.adding) {
            return;
        }
        this.state.adding = true;
        try {
            const added = await this.props.onAdd(this.state.partner, reservations);
            if (added) {
                this.props.close();
            }
        } finally {
            this.state.adding = false;
        }
    }
}

// ── Parche sobre ProductScreen ────────────────────────────────────────────────
patch(ProductScreen.prototype, {
    setup() {
        super.setup();
        this._dialog = useService("dialog");
        this._orm = useService("orm");
        this._notification = useService("notification");
        this._pos = usePos();
    },

    _notifyError(message) {
        console.warn("[Reservas]", message);
        this._notification.add(message, { type: "danger", sticky: true });
    },

    openReservations() {
        const order = this._pos.selectedOrder;
        if (!order) {
            console.warn("[Reservas] No hay orden activa");
            return;
        }
        // Reservas ya agregadas a la orden (vínculo por
        // rehalife_reservation_ids_json; el Many2one solo en órdenes viejas).
        const addedReservationIds = new Set();
        for (const line of order.lines || []) {
            for (const id of lineReservationIds(line)) {
                addedReservationIds.add(id);
            }
        }
        const orderPartner = order.get_partner();
        const props = {
            addedReservationIds,
            partnerLocked: addedReservationIds.size > 0 && Boolean(orderPartner),
            onAdd: (partner, reservations) => this._addReservationsToOrder(partner, reservations),
        };
        if (orderPartner) {
            props.partner = { id: orderPartner.id, name: orderPartner.name };
        }
        this._dialog.add(ReservationDialog, props);
    },

    async _loadPartner(partnerId) {
        const pos = this._pos;
        let partner = pos.models["res.partner"]?.getBy("id", partnerId);
        if (!partner) {
            // Mismo patrón que antes de la Fase 3 (probado): leer y registrar
            // el contacto en el store reactivo del POS.
            const [partnerData] = await this._orm.read("res.partner", [partnerId], []);
            if (partnerData) {
                partner = pos.models["res.partner"].create(partnerData);
            }
        }
        return partner;
    },

    async _loadProduct(productId) {
        const pos = this._pos;
        let product = pos.models["product.product"]?.getBy("id", productId);
        if (!product) {
            try {
                // PosData.read carga el registro en los modelos del POS.
                const loaded = await pos.data.read("product.product", [productId]);
                product = Array.isArray(loaded) ? loaded[0] : null;
            } catch (e) {
                console.warn("[Reservas] No se pudo cargar el producto", productId, e);
            }
        }
        return product || null;
    },

    /**
     * Agrega las reservas elegidas: vuelve a pedir al servidor los datos de
     * cobro (pueden haber cambiado desde que se abrió el diálogo) y arma UNA
     * línea por (producto, precio). Si alguna ya no es cobrable, no agrega
     * NADA y muestra el motivo. Devuelve true si se agregaron.
     */
    async _addReservationsToOrder(partnerInfo, reservations) {
        const pos = this._pos;
        const order = pos.selectedOrder;
        if (!order) {
            this._notifyError("No hay una orden activa.");
            return false;
        }

        let charge;
        try {
            charge = await this._orm.call(
                "rehalife.reservation", "get_pos_charge_info", [reservations.map((r) => r.id)]
            );
        } catch (e) {
            this._notifyError(`No se pudo verificar el cobro de las reservas (${e?.message || e}).`);
            return false;
        }
        const notChargeable = reservations.filter((res) => !charge[res.id]?.chargeable);
        if (notChargeable.length) {
            this._notifyError(
                "No se agregó ninguna reserva. No se pueden cobrar: " +
                notChargeable.map((res) =>
                    `${formatDate(res.reservation_date)} ${res.reservation_time || ""} — ` +
                    (charge[res.id]?.reason || charge[res.id]?.message || "sin datos de cobro")
                ).join(" | ")
            );
            return false;
        }

        // ── 1. Paciente de la orden ────────────────────────────────────────
        const currentPartner = order.get_partner();
        if (!currentPartner || currentPartner.id !== partnerInfo.id) {
            const hasReservationLines = order.lines.some((line) => lineReservationIds(line).length);
            if (currentPartner && hasReservationLines) {
                this._notifyError(
                    `La venta ya tiene reservas de ${currentPartner.name}: no se pueden mezclar ` +
                    "reservas de otro paciente en la misma venta."
                );
                return false;
            }
            let partner;
            try {
                partner = await this._loadPartner(partnerInfo.id);
            } catch (e) {
                console.warn("[Reservas] Error cargando partner:", e);
            }
            if (!partner) {
                this._notifyError(
                    `No se pudo asignar el paciente ${partnerInfo.name} a la venta. ` +
                    "No se agregó ninguna reserva."
                );
                return false;
            }
            order.set_partner(partner);
        }

        // ── 2. Agrupar por (producto, precio) ──────────────────────────────
        const groups = new Map();
        for (const res of reservations) {
            const info = charge[res.id];
            const price = Math.round((info.price_unit || 0) * 100) / 100;
            const key = `${info.product_id}|${price.toFixed(2)}`;
            if (!groups.has(key)) {
                groups.set(key, { info, price, reservations: [] });
            }
            groups.get(key).reservations.push(res);
        }

        // Productos primero: si falta alguno, no se agrega nada.
        const products = {};
        for (const { info } of groups.values()) {
            if (!(info.product_id in products)) {
                products[info.product_id] = await this._loadProduct(info.product_id);
            }
            if (!products[info.product_id]) {
                this._notifyError(
                    `El producto ${info.product_name} no está cargado en esta sesión del POS. ` +
                    "Recarga el POS para poder cobrar la reserva. No se agregó ninguna reserva."
                );
                return false;
            }
        }

        // ── 3. Una línea por grupo, qty = N reservas ───────────────────────
        const patientName = partnerInfo.name || "";
        for (const { info, price, reservations: groupRes } of groups.values()) {
            groupRes.sort((a, b) => sortKey(a).localeCompare(sortKey(b)));
            const n = groupRes.length;
            const service = groupRes[0].service_type_name || info.product_name || "Servicio";
            const dates = groupRes.map((res) => formatDate(res.reservation_date));
            const datesText = dates.length > 4
                ? `${dates[0]} … ${dates[dates.length - 1]}`
                : dates.join(", ");
            let name = `${service} × ${n} — ${patientName} — ${datesText}`;
            if (info.modalidad === "seguro") {
                name += ` — Copago ${money(price)} Bs. c/u`;
                if (info.line_note) {
                    name += ` (${info.line_note})`;
                }
            }

            // NOTA: pos.models["pos.order.line"].create() es un create() de bajo
            // nivel que NO pasa por order.add_product() (no calcula impuestos).
            // El servidor completa tax_ids si llega vacío (pos.order.line.create
            // en rehalife_pos.py). El Many2one rehalife_reservation_id NO se
            // usa: no llega al servidor (related_models.js, serialize).
            pos.models["pos.order.line"].create({
                order_id: order,
                product_id: products[info.product_id],
                qty: n,
                price_unit: price,
                price_type: "manual",
                rehalife_reservation_ids_json: JSON.stringify(groupRes.map((res) => res.id)),
                full_product_name: name,
            });
            console.log(`[Reservas] ✅ Línea agregada: ${n} reserva(s) a ${money(price)} Bs.`, groupRes.map((r) => r.id));
        }
        return true;
    },
});
