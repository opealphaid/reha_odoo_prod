/** @odoo-module */

import { AbstractAwaitablePopup } from "@point_of_sale/app/utils/abstract_awaitable_popup";
import { _t } from "@web/core/l10n/translation";

export class CustomTestPopup extends AbstractAwaitablePopup {
    static template = "custom_receipt.CustomTestPopup";
    static defaultProps = {
        confirmText: _t("Ok"),
        cancelText: _t("Cancel"),
        title: _t("Test Popup"),
        body: "",
    };
}