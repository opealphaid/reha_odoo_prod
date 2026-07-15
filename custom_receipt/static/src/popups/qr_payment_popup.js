/** @odoo-module */

import { Component, onWillUnmount, onMounted, useState } from "@odoo/owl";
import { Dialog } from "@web/core/dialog/dialog";
import { useService } from "@web/core/utils/hooks";
import { _t } from "@web/core/l10n/translation";

// Ventana de polling automatico: 90s observados en pruebas con el banco (ver
// banco-ganadero-qr-spec.md). El QR sigue siendo valido despues de esto hasta
// su expirationDate real; solo dejamos de refrescar solos.
const POLL_WINDOW_SECONDS = 90;
const POLL_INTERVAL_MS = 3500;

export class QrPaymentPopup extends Component {
    static template = "custom_receipt.QrPaymentPopup";
    static components = { Dialog };
    static props = {
        amount: Number,
        currency: { type: String, optional: true },
        currencySymbol: { type: String, optional: true },
        reference: { type: String, optional: true },
        getPayload: Function,
        close: Function,
    };

    setup() {
        this.orm = useService("orm");
        this.state = useState({
            // generating | waiting | paid | expired | error | cancelling
            status: "generating",
            qrId: null,
            qrImageBase64: null,
            secondsLeft: POLL_WINDOW_SECONDS,
            errorMessage: "",
            transactionNumber: null,
            payDate: null,
            payHour: null,
            confirmingCancel: false,
        });

        this._pollTimer = null;
        this._countdownTimer = null;

        onMounted(() => this._generateQr());
        onWillUnmount(() => this._teardownTimers());
    }

    // ── Helpers ──────────────────────────────────────────────────────────
    _newTransactionId() {
        // Maximo 12 caracteres (spec del banco).
        return ("T" + Date.now().toString()).slice(-12);
    }

    _shortReference() {
        // Maximo 10 caracteres (spec del banco).
        return (this.props.reference || "POS").slice(-10);
    }

    _teardownTimers() {
        if (this._pollTimer) {
            clearInterval(this._pollTimer);
            this._pollTimer = null;
        }
        if (this._countdownTimer) {
            clearInterval(this._countdownTimer);
            this._countdownTimer = null;
        }
    }

    // ── Generacion del QR ────────────────────────────────────────────────
    async _generateQr() {
        this._teardownTimers();
        this.state.status = "generating";
        this.state.errorMessage = "";
        this.state.qrId = null;
        this.state.qrImageBase64 = null;
        this.state.secondsLeft = POLL_WINDOW_SECONDS;

        try {
            const result = await this.orm.call("pos.order", "ganadero_create_qr_order", [
                this.props.amount,
                this._shortReference(),
                this._newTransactionId(),
                this.props.currency || "BOB",
            ]);

            if (!result || !result.qr_id || !result.qr_image_base64) {
                throw new Error(_t("No se pudo generar el codigo QR."));
            }

            this.state.qrId = result.qr_id;
            this.state.qrImageBase64 = result.qr_image_base64;
            this.state.status = "waiting";
            this._startPolling();
        } catch (error) {
            this.state.status = "error";
            this.state.errorMessage = this._extractErrorMessage(error);
        }
    }

    _extractErrorMessage(error) {
        return (
            error?.data?.message ||
            error?.message?.data?.message ||
            error?.message ||
            _t("Ocurrio un error inesperado al generar el pago QR.")
        );
    }

    // ── Polling de estado ────────────────────────────────────────────────
    _startPolling() {
        this._teardownTimers();

        this._countdownTimer = setInterval(() => {
            this.state.secondsLeft -= 1;
            if (this.state.secondsLeft <= 0) {
                this._teardownTimers();
                if (this.state.status === "waiting") {
                    this.state.status = "expired";
                }
            }
        }, 1000);

        this._pollTimer = setInterval(() => this._checkStatus(), POLL_INTERVAL_MS);
        // Primera verificacion inmediata, sin esperar el primer intervalo.
        this._checkStatus();
    }

    async _checkStatus() {
        if (!this.state.qrId) {
            return;
        }
        try {
            const result = await this.orm.call("pos.order", "ganadero_get_qr_status", [
                this.state.qrId,
            ]);
            if (result.order_state === "2") {
                this._teardownTimers();
                this.state.status = "paid";
                this.state.transactionNumber = result.transaction_number;
                this.state.payDate = result.pay_date;
                this.state.payHour = result.pay_hour;
            } else if (result.order_state === "3") {
                this._teardownTimers();
                this.state.status = "cancelled";
            }
            // order_state === '1' (registrado/pendiente): seguimos esperando.
        } catch (error) {
            // Un error puntual de la consulta de estado no debe tumbar el
            // polling; solo lo registramos y seguimos intentando.
            console.warn("[Pago QR] Error verificando estado:", error);
        }
    }

    async onClickVerifyNow() {
        await this._checkStatus();
    }

    async onClickNewQr() {
        if (this.state.qrId && this.state.status === "expired") {
            try {
                await this.orm.call("pos.order", "ganadero_cancel_qr_order", [this.state.qrId]);
            } catch (error) {
                // Si ya no se puede anular (ej. venció o ya fue pagado en el
                // banco), igual generamos uno nuevo; no bloqueamos al cajero.
                console.warn("[Pago QR] No se pudo anular el QR anterior:", error);
            }
        }
        await this._generateQr();
    }

    onClickAskCancel() {
        this.state.confirmingCancel = true;
    }

    onClickDismissCancel() {
        this.state.confirmingCancel = false;
    }

    async onClickConfirmCancel() {
        this.state.confirmingCancel = false;
        if (this.state.qrId && ["waiting", "expired"].includes(this.state.status)) {
            try {
                await this.orm.call("pos.order", "ganadero_cancel_qr_order", [this.state.qrId]);
            } catch (error) {
                console.warn("[Pago QR] No se pudo anular el QR al cancelar:", error);
            }
        }
        this._teardownTimers();
        this.props.close();
    }

    onClickConfirmPayment() {
        this.props.getPayload({
            qrId: this.state.qrId,
            transactionNumber: this.state.transactionNumber,
            payDate: this.state.payDate,
            payHour: this.state.payHour,
        });
        this.props.close();
    }

    onClickRetryAfterError() {
        this._generateQr();
    }

    onClickCloseAfterError() {
        this.props.close();
    }
}
