/** @odoo-module */

import { Picker, usePicker } from "@mail/core/common/picker";
import { markEventHandled } from "@web/core/utils/misc";
import { Component, useRef } from "@odoo/owl";

export class SocialPostCommentEmoji extends Component {
    static components = { Picker };
    static template = 'viin_social.SocialPostCommentEmoji';
    static props = {};

    constructor() {
        super(...arguments);
        this.ev = null;
    }

    setup() {
        this.emojiButton = useRef("emoji-button");
        this.picker = usePicker(this.pickerSettings);
        super.setup();
    }

    onClickAddEmoji(ev) {
        this.ev = ev;
        markEventHandled(ev, "Composer.onClickAddEmoji");
    }

    get pickerSettings() {
        return {
            anchor: this.props.mode === "extended" ? undefined : this.mainActionsRef,
            buttons: [this.emojiButton],
            close: () => {},
            pickers: { emoji: (emoji) => this.addEmoji(emoji) },
            position: this.props.mode === "extended" ? "bottom-start" : "top-end",
        };
    }

    addEmoji(str) {
        var ev = this.ev;
        ev.preventDefault();
        var currentElement = ev.target;
        var textareaElement = currentElement.closest(".comment_input").querySelector("textarea");
        if (textareaElement) {
            textareaElement.value += str;
        }
    }
}
