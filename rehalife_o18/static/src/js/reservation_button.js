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
            reservations: [],
            loading: true,
            searchName:   '',
            searchBranch: '',
            // Precio de lista del servicio por service_type_external_id, solo
            // para mostrar en la tabla (ver _loadServicePrices).
            priceByService: {},
            // Sucursal del usuario (get_pos_branch_info). Solo informativo:
            // el filtro real de las reservas lo hace la regla de registro.
            branchInfo: { restricted: false, branch_id: false, branch_name: '' },
            // Estado del servicio por reserva (get_pos_service_status). null =
            // no se pudo obtener: sin etiquetas y "Cobrar" habilitado (el
            // control al cobrar y el del servidor se ejecutan igual).
            serviceStatus: null,
        });
        onMounted(() => {
            this._load();
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

    // ── Estado del servicio (badge y bloqueo de "Cobrar") ──────────────────
    serviceInfo(res) {
        return this.state.serviceStatus ? this.state.serviceStatus[res.id] || null : null;
    }

    /** False solo si se conoce el estado y no está listo. */
    canCharge(res) {
        const info = this.serviceInfo(res);
        return !info || info.status === 'ready';
    }

    serviceBadge(res) {
        const info = this.serviceInfo(res);
        if (!info) {
            return null;
        }
        const badges = {
            ready:           { cls: 'badge bg-success', label: 'Listo para cobrar' },
            not_homologated: { cls: 'badge bg-warning text-dark', label: 'No homologado (SIAT)' },
            not_in_pos:      { cls: 'badge bg-warning text-dark', label: 'No disponible en POS' },
            not_found:       { cls: 'badge bg-danger', label: 'Servicio no encontrado' },
        };
        return badges[info.status] || null;
    }

    /** Recepcionista restringido sin sucursal: no se listan reservas. */
    get noBranchAssigned() {
        return this.state.branchInfo.restricted && !this.state.branchInfo.branch_id;
    }

    async _loadBranchInfo() {
        try {
            this.state.branchInfo = await this.orm.call(
                "rehalife.reservation", "get_pos_branch_info", []
            );
            if (this.state.branchInfo.restricted) {
                // El campo "Buscar por sucursal" se oculta: que no quede
                // filtrando con algo escrito antes de recibir esta info.
                this.state.searchBranch = '';
            }
        } catch (e) {
            // Sin esta info el diálogo se comporta como antes; la regla de
            // registro sigue filtrando las reservas en el servidor.
            console.warn("[Reservas] No se pudo obtener la sucursal del usuario:", e);
        }
    }

    async _load() {
        try {
            await this._loadBranchInfo();
            if (this.noBranchAssigned) {
                return;
            }
            this.state.reservations = await this.orm.searchRead(
                "rehalife.reservation",
                [
                    ["invoice_status", "=", "pending"],
                    ["status",         "in", ["IN_ROOM", "IN_CONSULTATION", "COMPLETED"]],
                ],
                [
                    "id", "partner_id", "reservation_date",
                    "reservation_time", "end_time", "sub_specialty",
                    "doctor_name", "branch_name", "environment_name",
                    "service_type_external_id", "service_type_name",
                    "modalidad", "monto_a_pagar_paciente", "monto_cobertura_seguro",
                ],
                { limit: 50, order: "reservation_date desc" }
            );
            await this._loadServiceStatus();
            await this._loadServicePrices();
        } finally {
            this.state.loading = false;
        }
    }

    /** Estado del servicio de todas las reservas listadas, en UNA llamada. */
    async _loadServiceStatus() {
        const ids = this.state.reservations.map(res => res.id);
        if (!ids.length) {
            return;
        }
        try {
            this.state.serviceStatus = await this.orm.call(
                "rehalife.reservation", "get_pos_service_status", [ids]
            );
        } catch (e) {
            console.warn("[Reservas] No se pudo obtener el estado de los servicios:", e);
        }
    }

    /**
     * Precio de lista de cada servicio de las reservas listadas, en UNA sola
     * consulta. Mismo criterio con el que el cobro resuelve el producto
     * (product por rehalife_external_id = service_type_external_id, disponible
     * en POS y activo). Es solo visual: el precio que se cobra lo sigue
     * calculando `onSelect` como siempre. Si falla, la tabla muestra "—".
     */
    async _loadServicePrices() {
        const ids = [...new Set(
            this.state.reservations
                .map(res => res.service_type_external_id)
                .filter(Boolean)
        )];
        if (!ids.length) {
            return;
        }
        try {
            const products = await this.orm.searchRead(
                "product.product",
                [
                    ["product_tmpl_id.rehalife_external_id", "in", ids],
                    ["product_tmpl_id.available_in_pos", "=", true],
                    ["active", "=", true],
                ],
                ["list_price", "rehalife_external_id"],
            );
            const prices = {};
            for (const product of products) {
                // El cobro usa el primero que devuelve la búsqueda (limit 1).
                if (!(product.rehalife_external_id in prices)) {
                    prices[product.rehalife_external_id] = product.list_price || 0;
                }
            }
            this.state.priceByService = prices;
        } catch (e) {
            console.warn("[Reservas] No se pudieron cargar los precios de los servicios:", e);
        }
    }

    /** Precio de lista del servicio de la reserva, o null si no hay producto. */
    servicePrice(res) {
        const price = this.state.priceByService[res.service_type_external_id];
        return price === undefined ? null : price;
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
        // Reservas ya agregadas a la orden. El Many2one solo existe en el
        // navegador (no viaja al servidor, ver nota en el create de la línea);
        // una orden recargada desde el servidor trae el vínculo solo en
        // rehalife_reservation_ids_json.
        const addedReservationIds = new Set();
        for (const line of order?.lines || []) {
            const m2o = line.rehalife_reservation_id?.id ?? line.rehalife_reservation_id;
            if (m2o) {
                addedReservationIds.add(m2o);
            }
            if (line.rehalife_reservation_ids_json) {
                try {
                    for (const id of JSON.parse(line.rehalife_reservation_ids_json) || []) {
                        addedReservationIds.add(id);
                    }
                } catch {
                    console.warn("[Reservas] rehalife_reservation_ids_json inválido en la línea", line);
                }
            }
        }

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

                // ── 0. El servicio debe estar listo (se vuelve a consultar al
                //       cobrar; si no está listo, no se agrega nada) ─────────
                let info;
                try {
                    const status = await orm.call(
                        "rehalife.reservation", "get_pos_service_status", [[res.id]]
                    );
                    info = status[res.id];
                } catch (e) {
                    console.warn("[Reservas] No se pudo verificar el servicio:", e);
                    this._notification.add(
                        `No se pudo verificar el servicio de la reserva (${e?.message || e}).`,
                        { type: "danger", sticky: true }
                    );
                    return;
                }
                if (!info || info.status !== "ready") {
                    this._notification.add(
                        info?.message || "El servicio de la reserva no está listo para cobrarse.",
                        { type: "danger", sticky: true }
                    );
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
                    const productId = info.product_id;
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
                            : (info.list_price || 0);
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

                        // NOTA: pos.models["pos.order.line"].create() es un create()
                        // de bajo nivel que NO pasa por order.add_product() (el flujo
                        // nativo de Odoo que calcula los impuestos del producto), así
                        // que la línea nace sin tax_ids. Intentar fijar tax_ids acá a
                        // mano rompía el render del POS (el modelo reactivo espera un
                        // formato interno específico para los many2many). Se resuelve
                        // en el servidor en su lugar — ver pos.order.line.create()
                        // en rehalife_o18/models/rehalife_pos.py, que completa
                        // tax_ids con los impuestos del producto si llega vacío.
                        pos.models["pos.order.line"].create({
                            order_id:   order,
                            product_id: product,
                            qty:        1,
                            price_unit: priceUnit,
                            rehalife_reservation_id: res.id,
                            // El vínculo que llega al servidor. El POS de Odoo 18
                            // serializa un Many2one hacia un modelo que no carga
                            // (rehalife.reservation) como false
                            // (point_of_sale/static/src/app/models/related_models.js,
                            // serialize): el Many2one de arriba solo sirve en el
                            // navegador. Un Char sí viaja tal cual; el servidor lo
                            // convierte al Many2many rehalife_reservation_ids.
                            rehalife_reservation_ids_json: JSON.stringify([res.id]),
                            full_product_name: nombreLinea,
                        });
                        console.log("[Reservas] ✅ Producto agregado, precio:", priceUnit);
                        console.log(`[Reservas] ✅ Reserva ${res.id} vinculada a la línea`);
                    } else {
                        const msg = `El producto ${info.product_name} no está cargado en esta sesión del POS. Recarga el POS para poder cobrar la reserva.`;
                        console.warn("[Reservas]", msg);
                        this._notification.add(msg, { type: "danger", sticky: true });
                    }
                } catch (e) {
                    console.warn("[Reservas] Error agregando producto:", e);
                    this._notification.add(
                        `No se pudo agregar la reserva a la orden (${e?.message || e}).`,
                        { type: "danger", sticky: true }
                    );
                }
            },
        });
    },
});