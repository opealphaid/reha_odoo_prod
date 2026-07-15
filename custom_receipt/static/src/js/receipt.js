/** @odoo-module */
import { OrderReceipt } from "@point_of_sale/app/screens/receipt_screen/receipt/order_receipt";
import { patch } from "@web/core/utils/patch";
import { loadJS } from "@web/core/assets";
import { useService } from "@web/core/utils/hooks";

let QRCodeLib = null;

// Cache global para almacenar datos SIAT
const SIAT_CACHE = new Map();

async function loadQRCodeLibrary() {
    if (!QRCodeLib) {
        try {
            await loadJS("https://cdnjs.cloudflare.com/ajax/libs/qrcodejs/1.0.0/qrcode.min.js");
            QRCodeLib = window.QRCode;
            console.log("✅ Librería QRCode cargada");
        } catch (error) {
            console.error("❌ Error cargando librería QRCode:", error);
        }
    }
    return QRCodeLib;
}

async function generateQRCodeBase64(text) {
    console.log("🟡 Generando QR con texto:", text);
    await loadQRCodeLibrary();

    if (QRCodeLib) {
        try {
            const tempDiv = document.createElement('div');
            tempDiv.style.display = 'none';
            document.body.appendChild(tempDiv);

            const qrcode = new QRCodeLib(tempDiv, {
                text: text,
                width: 200,
                height: 200,
                colorDark: "#000000",
                colorLight: "#ffffff",
                correctLevel: QRCodeLib.CorrectLevel.M
            });

            await new Promise(resolve => setTimeout(resolve, 100));

            const canvas = tempDiv.querySelector('canvas');
            if (canvas) {
                const base64 = canvas.toDataURL('image/png');
                console.log("✅ QR real generado:", base64.substring(0, 100));
                document.body.removeChild(tempDiv);
                return base64;
            }
        } catch (error) {
            console.error("❌ Error generando QR:", error);
        }
    }

    return generatePlaceholderQR(text);
}

function generatePlaceholderQR(text) {
    console.log("⚠️ Usando placeholder para QR");
    const canvas = document.createElement('canvas');
    const size = 200;
    canvas.width = size;
    canvas.height = size;
    const ctx = canvas.getContext('2d');

    ctx.fillStyle = 'white';
    ctx.fillRect(0, 0, size, size);
    ctx.strokeStyle = 'black';
    ctx.lineWidth = 2;
    ctx.strokeRect(10, 10, size-20, size-20);
    ctx.fillStyle = 'black';
    ctx.font = 'bold 16px Arial';
    ctx.textAlign = 'center';
    ctx.fillText('QR CODE', size/2, size/2 - 20);
    ctx.font = '12px Arial';
    ctx.fillText(text.substring(0, 25), size/2, size/2);
    ctx.fillText(text.substring(25, 50), size/2, size/2 + 20);

    return canvas.toDataURL('image/png');
}

patch(OrderReceipt.prototype, {
    setup() {
        super.setup();
        this.orm = useService("orm");

        console.log("=".repeat(100));
        console.log("🟣 RECEIPT SETUP - Datos recibidos");
        console.log("=".repeat(100));
        console.log("Props completos:", this.props);
        console.log("Data:", this.props.data);
        console.log("Nombre orden:", this.props.data?.name);
        console.log("To Invoice:", this.props.data?.to_invoice);
        console.log("=".repeat(100));

        // Primero intentar cargar desde cache INMEDIATAMENTE
        const orderName = this.props.data?.name;
        if (orderName && SIAT_CACHE.has(orderName)) {
            console.log("⚡ Cargando desde cache inmediatamente");
            const cached = SIAT_CACHE.get(orderName);
            this.props.data.custom_qr_code = cached.custom_qr_code;
            this.props.data.siat_info = cached.siat_info;
            this.props.data.footer = cached.footer; // ✅ Cargar footer del cache
        }

        // Luego cargar/actualizar datos SIAT
        this.loadSiatData();
    },

    async getRandomLeyenda() {
        try {
            console.log("🎲 Obteniendo leyenda aleatoria...");

            // Obtener todas las leyendas activas
            const leyendas = await this.orm.searchRead(
                "alpha.siat.leyenda",
                [["active", "=", true]],
                ["id", "descripcion_leyenda", "codigo_actividad"],
                { limit: 0 } // Sin límite para obtener todas
            );

            if (leyendas && leyendas.length > 0) {
                // Seleccionar una aleatoria
                const randomIndex = Math.floor(Math.random() * leyendas.length);
                const randomLeyenda = leyendas[randomIndex];
                console.log("✅ Leyenda aleatoria seleccionada:", randomLeyenda.descripcion_leyenda);
                return randomLeyenda.descripcion_leyenda;
            } else {
                console.warn("⚠️ No se encontraron leyendas activas");
                return "Ley N° 453: Tienes derecho a un trato equitativo sin discriminación en la oferta de servicios.";
            }
        } catch (error) {
            console.error("❌ Error obteniendo leyenda aleatoria:", error);
            return "Ley N° 453: Tienes derecho a un trato equitativo sin discriminación en la oferta de servicios.";
        }
    },

    async loadSiatData() {
        try {
            const orderName = this.props.data?.name;

            if (!orderName) {
                console.warn("⚠️ No se encontró nombre de orden");
                this.generateFallbackQR();
                return;
            }

            // 🎲 OBTENER LEYENDA ALEATORIA AL INICIO
            const leyendaAleatoria = await this.getRandomLeyenda();
            this.props.data.footer = leyendaAleatoria;
            console.log("📝 Leyenda asignada:", leyendaAleatoria);

            // Verificar si ya tenemos datos en cache
            if (SIAT_CACHE.has(orderName)) {
                console.log("📦 Usando datos SIAT desde cache (ya cargado antes)");
                const cached = SIAT_CACHE.get(orderName);
                this.props.data.custom_qr_code = cached.custom_qr_code;
                this.props.data.siat_info = cached.siat_info;
                // Usar la leyenda del cache si existe, sino usar la nueva
                if (cached.footer) {
                    this.props.data.footer = cached.footer;
                }
                // Forzar render para asegurar que se muestre
                setTimeout(() => this.render(), 50);
                return;
            }

            console.log(`🔍 Buscando orden: ${orderName}`);

            // Buscar la orden en el backend
            const orders = await this.orm.searchRead(
                "pos.order",
                [["pos_reference", "=", orderName]],
                [
                    "id",
                    "name",
                    "pos_reference",
                    "to_invoice",
                    "siat_cuf",
                    "siat_numero_factura",
                    "siat_codigo_recepcion",
                    "siat_estado_envio",
                    "siat_fecha_envio",
                    "partner_id",
                    "company_id"
                ],
                { limit: 1 }
            );

            console.log("📦 Órdenes encontradas:", orders);

            if (orders && orders.length > 0) {
                const order = orders[0];
                console.log("✅ Orden encontrada:", order);

                // Verificar si tiene factura SIAT (por el CUF)
                if (order.siat_cuf) {
                    console.log("🎫 Orden tiene factura SIAT");
                    console.log("  CUF:", order.siat_cuf);
                    console.log("  Número:", order.siat_numero_factura);

                    // Obtener datos de compañía y partner
                    const company = await this.orm.read(
                        "res.company",
                        [order.company_id[0]],
                        ["vat", "name"]
                    );

                    const partner = await this.orm.read(
                        "res.partner",
                        [order.partner_id[0]],
                        ["vat", "name"]
                    );

                    console.log("🏢 Compañía:", company[0]);
                    console.log("👤 Cliente:", partner[0]);

                    // Construir URL del QR de SIAT
                    const qrUrl = `https://pilotosiat.impuestos.gob.bo/consulta/QR?nit=${company[0].vat}&cuf=${order.siat_cuf}&numero=${order.siat_numero_factura}&t=1`;

                    console.log("🔗 URL QR SIAT:", qrUrl);

                    // Generar QR con la URL de SIAT
                    const qrBase64 = await generateQRCodeBase64(qrUrl);

                    // Preparar datos SIAT
                    const siatInfo = {
                        numero_factura: order.siat_numero_factura,
                        cuf: order.siat_cuf,
                        codigo_recepcion: order.siat_codigo_recepcion || '',
                        fecha_emision: order.siat_fecha_envio || '',
                        estado: order.siat_estado_envio || '',
                        empresa_nit: company[0].vat,
                        empresa_razon_social: company[0].name,
                        cliente_nit: partner[0].vat || '',
                        cliente_razon_social: partner[0].name,
                    };

                    // GUARDAR EN CACHE para que persista al imprimir
                    SIAT_CACHE.set(orderName, {
                        custom_qr_code: qrBase64,
                        siat_info: siatInfo,
                        footer: this.props.data.footer // ✅ Guardar la leyenda en cache
                    });

                    // Inyectar datos en props
                    this.props.data.custom_qr_code = qrBase64;
                    this.props.data.siat_info = siatInfo;

                    console.log("✅ Datos SIAT inyectados:");
                    console.log(this.props.data.siat_info);

                    // Forzar re-render
                    this.render();

                } else {
                    console.log("⚠️ Orden sin factura SIAT (no tiene CUF) - usando QR genérico");
                    this.generateFallbackQR();
                }
            } else {
                console.warn("⚠️ No se encontró la orden");
                this.generateFallbackQR();
            }

        } catch (error) {
            console.error("❌ Error cargando datos SIAT:", error);
            this.generateFallbackQR();
        }
    },

    async generateFallbackQR() {
        const qrText = `FACTURA - ${this.props.data.name} - ALPHA SYSTEMS - BOLIVIA`;
        const qrBase64 = await generateQRCodeBase64(qrText);

        // También guardar en cache el fallback con la leyenda
        SIAT_CACHE.set(this.props.data.name, {
            custom_qr_code: qrBase64,
            siat_info: null,
            footer: this.props.data.footer // ✅ Guardar la leyenda también en el fallback
        });

        this.props.data.custom_qr_code = qrBase64;
        console.log("✅ QR genérico generado");
        this.render();
    }
});