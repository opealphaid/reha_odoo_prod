import { patch } from "@web/core/utils/patch";
import { WebClient } from "@web/webclient/webclient";
import { useService } from "@web/core/utils/hooks";

patch(WebClient.prototype, {
	/**
	* @override
	*/
	setup() {
		super.setup();
		this.companyService = useService("company");
		// Update Favicons
		const favicon = `/web/image/res.company/${this.companyService.currentCompany.id}/favicon`;
		const icons = document.querySelectorAll("link[rel*='icon']");
		for (const icon of icons) {
			if (icon.rel != 'apple-touch-icon')
				icon.href = favicon
		}
	}
});
