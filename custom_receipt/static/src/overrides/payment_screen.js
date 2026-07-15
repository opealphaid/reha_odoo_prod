/** @odoo-module */

import { PaymentScreen } from "@point_of_sale/app/screens/payment_screen/payment_screen";
import { patch } from "@web/core/utils/patch";
import { makeAwaitable } from "@point_of_sale/app/store/make_awaitable_dialog";
import { AlertDialog } from "@web/core/confirmation_dialog/confirmation_dialog";
import { QrPaymentPopup } from "@custom_receipt/popups/qr_payment_popup";
import { _t } from "@web/core/l10n/translation";

patch(PaymentScreen.prototype, {
    async openCustomWizard() {
        const order = this.currentOrder;
        const due = order.get_due();

        if (due <= 0) {
            this.dialog.add(AlertDialog, {
                title: _t("Nada por cobrar"),
                body: _t("Esta orden no tiene saldo pendiente de pago."),
            });
            return;
        }

        // El QR no depende de un metodo de pago propio: el cobro se registra
        // con cualquier metodo ya configurado en el POS (no importa cual
        // quede en el registro contable, el QR solo es la forma en que el
        // cliente paga fisicamente).
        const qrPaymentMethod = this.pos.config.payment_method_ids[0];
        if (!qrPaymentMethod) {
            this.dialog.add(AlertDialog, {
                title: _t("Metodo de pago no disponible"),
                body: _t("Este punto de venta no tiene ningun metodo de pago configurado."),
            });
            return;
        }

        const currency = this.pos.currency?.name === "USD" ? "USD" : "BOB";

        const payload = await makeAwaitable(this.dialog, QrPaymentPopup, {
            amount: due,
            currency,
            currencySymbol: this.pos.currency?.symbol || "Bs",
            reference: order.name || "",
        });

        if (!payload) {
            // El cajero cerro/cancelo el popup sin confirmar el pago: no se
            // agrega ninguna linea de pago, la orden queda como estaba.
            return;
        }

        const paymentline = order.add_paymentline(qrPaymentMethod);
        if (!paymentline) {
            this.dialog.add(AlertDialog, {
                title: _t("Error"),
                body: _t("Ya hay un pago en curso en esta orden."),
            });
            return;
        }

        // El pago QR ya fue confirmado por el banco: se valida la orden de
        // inmediato para que pase directo a la factura, sin que el cajero
        // tenga que hacer clic en "Validar" manualmente.
        await this.validateOrder(false);
    },
});
