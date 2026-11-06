/** @odoo-module **/

// Pagos anticipados, Fase 3: verificación en el servidor de las líneas con
// reservas ANTES de cobrar, y bloqueos de la UI que evitan que una línea
// quede con una cantidad distinta a sus reservas.
//
// La defensa definitiva sigue siendo el servidor (pos.order
// _rehalife_check_before_paid, con bloqueo de filas). Esto solo evita llegar
// a cobrar (sobre todo por QR, donde el banco ya cobró) una venta que el
// servidor va a rechazar.

import { patch } from "@web/core/utils/patch";
import { AlertDialog } from "@web/core/confirmation_dialog/confirmation_dialog";
import { PosStore } from "@point_of_sale/app/store/pos_store";
import { PaymentScreen } from "@point_of_sale/app/screens/payment_screen/payment_screen";
import { PosOrderline } from "@point_of_sale/app/models/pos_order_line";
import { OrderSummary } from "@point_of_sale/app/screens/product_screen/order_summary/order_summary";
import { TicketScreen } from "@point_of_sale/app/screens/ticket_screen/ticket_screen";

export const REFUND_MSG = "Las reservas pagadas no se devuelven; deben reprogramarse.";

/**
 * Ids de reserva de una línea. El vínculo que llega al servidor es SIEMPRE
 * rehalife_reservation_ids_json (ver CLAUDE.MD, corrección Fase 2); el
 * Many2one solo existe en órdenes antiguas o en el navegador.
 */
export function lineReservationIds(line) {
    const ids = new Set();
    if (!line) {
        return [];
    }
    const m2o = line.rehalife_reservation_id?.id ?? line.rehalife_reservation_id;
    if (typeof m2o === "number" && m2o > 0) {
        ids.add(m2o);
    }
    if (line.rehalife_reservation_ids_json) {
        try {
            for (const id of JSON.parse(line.rehalife_reservation_ids_json) || []) {
                ids.add(id);
            }
        } catch {
            console.warn("[Reservas] rehalife_reservation_ids_json inválido en la línea", line);
        }
    }
    return [...ids];
}

export function lineHasReservations(line) {
    return lineReservationIds(line).length > 0;
}

function isRefundOfReservations(line) {
    return Boolean(line.refunded_orderline_id) && lineHasReservations(line.refunded_orderline_id);
}

export function orderHasReservationLines(order) {
    return Boolean(
        order?.lines?.some((line) => lineHasReservations(line) || isRefundOfReservations(line))
    );
}

function showErrors(dialog, title, errors) {
    dialog.add(AlertDialog, {
        title,
        body: errors.map((e) => `• ${e}`).join("\n"),
    });
}

/**
 * Verifica en el servidor las líneas con reservas de la orden.
 * Devuelve true si se puede seguir. Ventas sin reservas: true sin llamar al
 * servidor (no cambia nada para ellas). Sin conexión con Odoo: false.
 */
export async function checkOrderReservations(pos, dialog, order) {
    if (!orderHasReservationLines(order)) {
        return true;
    }
    if (order.lines.some((line) => isRefundOfReservations(line))) {
        showErrors(dialog, "No se puede devolver", [REFUND_MSG]);
        return false;
    }
    const lines = order.lines
        .filter((line) => lineHasReservations(line))
        .map((line) => ({
            product_id: line.product_id?.id,
            qty: line.qty,
            price_unit: line.price_unit,
            reservation_ids: lineReservationIds(line),
            label: line.full_product_name || line.product_id?.display_name || "",
        }));
    let result;
    try {
        result = await pos.data.call("pos.order.line", "check_reservations_payable", [
            order.get_partner()?.id || false,
            order.uuid,
            lines,
        ]);
    } catch (e) {
        console.warn("[Reservas] No se pudo verificar las reservas en el servidor:", e);
        showErrors(dialog, "Sin conexión con el servidor", [
            "Las ventas con reservas necesitan verificarse en el servidor de Odoo antes de " +
                "cobrarse y no hay conexión. Vuelve a intentarlo cuando se recupere la " +
                "conexión (el resto de ventas del POS no se afecta).",
        ]);
        return false;
    }
    if (!result?.ok) {
        showErrors(dialog, "No se puede cobrar la venta", result?.errors?.length
            ? result.errors
            : ["El servidor rechazó las reservas de la venta."]);
        return false;
    }
    return true;
}

// ── (1) Botón "Pago": antes de entrar a la PaymentScreen ─────────────────────
patch(PosStore.prototype, {
    async pay() {
        const order = this.get_order();
        if (order && !(await checkOrderReservations(this, this.dialog, order))) {
            return;
        }
        return super.pay(...arguments);
    },
});

// ── (2) QR de custom_receipt y (3) validateOrder ─────────────────────────────
patch(PaymentScreen.prototype, {
    /**
     * Gancho que custom_receipt (openCustomWizard) llama, si existe, ANTES de
     * abrir el popup / generar el QR: con el QR el banco cobra antes de
     * validar la orden, así que bloquear recién en validateOrder sería tarde.
     */
    async checkBeforeQrPayment() {
        return await checkOrderReservations(this.pos, this.dialog, this.currentOrder);
    },

    async validateOrder(isForceValidate) {
        if (!(await checkOrderReservations(this.pos, this.dialog, this.currentOrder))) {
            return;
        }
        return super.validateOrder(...arguments);
    },
});

// ── Una línea con reservas no se fusiona con otra ────────────────────────────
// Sin esto, agregar el mismo producto a mano subiría la qty de la línea de
// reservas sin agregar reservas (qty != reservas, el servidor la rechaza).
patch(PosOrderline.prototype, {
    can_be_merged_with(orderline) {
        if (lineHasReservations(this) || lineHasReservations(orderline)) {
            return false;
        }
        return super.can_be_merged_with(...arguments);
    },
});

// ── La cantidad de una línea con reservas no se edita ────────────────────────
function qtyLockedMessage(line) {
    const count = lineReservationIds(line).length;
    return {
        title: "Línea de reservas",
        body:
            `Esta línea cubre ${count} reserva(s): su cantidad no se puede cambiar. ` +
            "Para cobrar otras reservas, elimina la línea (⌫) y vuelve a agregarlas " +
            'desde el diálogo "Reservas".',
    };
}

patch(OrderSummary.prototype, {
    _setValue(val) {
        const line = this.currentOrder?.get_selected_orderline();
        if (
            line &&
            this.pos.numpadMode === "quantity" &&
            val !== "remove" &&
            lineHasReservations(line)
        ) {
            this.numberBuffer.reset();
            // Borrar la cantidad (⌫ o 0) elimina la línea completa: es la
            // forma de "quitar" reservas de la venta.
            if (val === "" || val === null || parseFloat(val) === 0) {
                return super._setValue("remove");
            }
            this.dialog.add(AlertDialog, qtyLockedMessage(line));
            return;
        }
        return super._setValue(...arguments);
    },

    async updateQuantityNumber(newQuantity) {
        const line = this.currentOrder?.get_selected_orderline();
        if (newQuantity !== null && line && lineHasReservations(line)) {
            if (newQuantity === 0) {
                this.currentOrder.removeOrderline(line);
                return true;
            }
            this.dialog.add(AlertDialog, qtyLockedMessage(line));
            return false;
        }
        return await super.updateQuantityNumber(...arguments);
    },
});

// ── TicketScreen: no se devuelven líneas con reservas ────────────────────────
patch(TicketScreen.prototype, {
    async onDoRefund() {
        const order = this.getSelectedOrder();
        if (order) {
            const reservationLines = order.lines.filter((line) => lineHasReservations(line));
            const toRefund = Object.values(this.pos.linesToRefund || {}).some(
                (detail) =>
                    detail.line?.order_id?.uuid === order.uuid &&
                    detail.qty &&
                    lineHasReservations(detail.line)
            );
            const soleItem =
                reservationLines.length > 0 && this._doesOrderHaveSoleItem(order);
            if (toRefund || soleItem) {
                this.dialog.add(AlertDialog, { title: "No se puede devolver", body: REFUND_MSG });
                return;
            }
        }
        return await super.onDoRefund(...arguments);
    },
});
