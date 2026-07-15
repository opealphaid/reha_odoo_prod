/** @odoo-module */

import { Component } from "@odoo/owl";
import { Dialog } from "@web/core/dialog/dialog";
import { _t } from "@web/core/l10n/translation";

export class ImagePopup extends Component {
    static template = "custom_receipt.ImagePopup";
    static components = { Dialog };
    static props = {
        title: { type: String, optional: true },
        body: { type: String, optional: true },
        imageUrl: { type: String, optional: true },
        close: Function,
    };

    onClickOk() {
        this.props.close();
    }
}