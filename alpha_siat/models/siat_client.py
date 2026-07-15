import logging
import requests
import xml.etree.ElementTree as ET
from dateutil import parser
from odoo import models
import gzip
import hashlib
import base64
from lxml import etree
from datetime import datetime, timezone, timedelta
import os
from odoo.modules.module import get_module_path

_logger = logging.getLogger(__name__)
class SiatClient(models.AbstractModel):
    _name = "alpha.siat.client"
    _description = "SIAT SOAP client helper"
    def _extract_soap_fault(self, xml_text):
        try:
            root = ET.fromstring(xml_text)
        except Exception:
            return None
        fault = root.find('.//{http://schemas.xmlsoap.org/soap/envelope/}Fault') or root.find('.//Fault')
        if fault is not None:
            fs = fault.findtext('faultstring') or fault.findtext(
                '{http://schemas.xmlsoap.org/soap/envelope/}faultstring')
            if fs:
                return fs.strip()
            detail = fault.find('detail')
            if detail is not None:
                try:
                    return ET.tostring(detail, encoding='unicode')
                except Exception:
                    return None
        return None
    def _extract_respuesta_cuis_messages(self, xml_text):
        try:
            root = ET.fromstring(xml_text)
        except Exception:
            return None
        ns = {'ns': 'https://siat.impuestos.gob.bo/'}
        res = root.find('.//ns:RespuestaCuis', ns) or root.find('.//RespuestaCuis')
        if res is None:
            return None
        msgs = []
        # try namespaced and non-namespaced mensaje nodes
        for m in res.findall('.//{https://siat.impuestos.gob.bo/}mensajesList') + res.findall('.//mensajesList'):
            desc = m.findtext('{https://siat.impuestos.gob.bo/}descripcion') or m.findtext('descripcion')
            if desc:
                msgs.append(desc.strip())
        return " | ".join(msgs) if msgs else None

    def call_cuis(self, company, config, timeout=30):
        if not config:
            return {"error": True, "mensajes": "No SIAT configuration provided", "raw": ""}
        url = (config.wsdl_codigos or '').strip()
        if url.endswith('?wsdl') or '?wsdl' in url:
            url = url.split('?wsdl')[0]

        token = config.token or ''
        body = f"""<soapenv:Envelope xmlns:soapenv="http://schemas.xmlsoap.org/soap/envelope/" xmlns:siat="https://siat.impuestos.gob.bo/">
  <soapenv:Header/>
  <soapenv:Body>
    <siat:cuis>
      <SolicitudCuis>
        <codigoAmbiente>{config.codigo_ambiente}</codigoAmbiente>
        <codigoModalidad>{config.modalidad}</codigoModalidad>
        <codigoPuntoVenta>{company.siat_codigo_punto_venta}</codigoPuntoVenta>
        <codigoSistema>{config.codigo_sistema or ''}</codigoSistema>
        <codigoSucursal>{company.siat_codigo_sucursal}</codigoSucursal>
        <nit>{(company.vat or '').strip()}</nit>
      </SolicitudCuis>
    </siat:cuis>
  </soapenv:Body>
</soapenv:Envelope>"""

        headers = {
            "Content-Type": "text/xml;charset=UTF-8",
            "apikey": f"TokenApi {token}"
        }
        try:
            r = requests.post(url, data=body.encode('utf-8'), headers=headers, timeout=timeout)
        except Exception as e:
            _logger.exception("SIAT HTTP request exception")
            return {"error": True, "mensajes": f"HTTP request exception: {e}", "raw": str(e), "http_status": None}

        # If HTTP error code, try to extract SOAP fault or RespuestaCuis messages and return them
        if r.status_code >= 400:
            _logger.warning("SIAT returned HTTP %s for URL %s", r.status_code, url)
            fault_msg = self._extract_soap_fault(r.text)
            resp_msgs = self._extract_respuesta_cuis_messages(r.text)
            combined = "; ".join(x for x in (fault_msg, resp_msgs) if x)
            if combined:
                return {"error": True, "http_status": r.status_code, "mensajes": f"SIAT error: {combined}",
                        "raw": r.text}
            return {"error": True, "http_status": r.status_code, "mensajes": f"SIAT returned HTTP {r.status_code}",
                    "raw": r.text}
        try:
            root = ET.fromstring(r.content)
        except Exception as e:
            _logger.exception("Failed parsing SIAT XML")
            return {"error": True, "http_status": r.status_code, "mensajes": f"Invalid XML response: {e}",
                    "raw": r.text}

        ns = {'ns': 'https://siat.impuestos.gob.bo/'}
        res_node = root.find('.//ns:RespuestaCuis', ns) or root.find('.//RespuestaCuis')
        if res_node is None:
            # fallback: try to find soap fault or messages
            fault_msg = self._extract_soap_fault(r.text)
            resp_msgs = self._extract_respuesta_cuis_messages(r.text)
            combined = "; ".join(x for x in (fault_msg, resp_msgs) if x)
            if combined:
                return {"error": True, "http_status": r.status_code,
                        "mensajes": f"SIAT response parsing issue: {combined}", "raw": r.text}
            return {"error": True, "http_status": r.status_code, "mensajes": "RespuestaCuis not found", "raw": r.text}
        codigo = res_node.findtext('ns:codigo', None, ns) or res_node.findtext('codigo')
        fecha = res_node.findtext('ns:fechaVigencia', None, ns) or res_node.findtext('fechaVigencia')

        msgs = []
        for m in res_node.findall('.//{https://siat.impuestos.gob.bo/}mensajesList') + res_node.findall(
                './/mensajesList'):
            desc = m.findtext('{https://siat.impuestos.gob.bo/}descripcion') or m.findtext('descripcion')
            if desc:
                msgs.append(desc.strip())
        mensajes_text = " | ".join(msgs) if msgs else ''

        if not codigo:
            combined = mensajes_text or self._extract_soap_fault(r.text) or r.text
            return {"error": True, "http_status": r.status_code,
                    "mensajes": f"No 'codigo' in SIAT response. Details: {combined}", "raw": r.text}
        parsed_fecha = None
        try:
            parsed_fecha = parser.parse(fecha).strftime("%Y-%m-%d %H:%M:%S") if fecha else None
        except Exception:
            parsed_fecha = fecha

        return {"error": False, "codigo": codigo, "vigencia": parsed_fecha, "mensajes": mensajes_text or '',
                "raw": r.text}

    def call_cufd(self, company, config, cuis, timeout=30):
        """
        Call SIAT CUFD web service

        :param company: res.company record
        :param config: alpha.siat.config record
        :param cuis: CUIS code string
        :param timeout: request timeout in seconds
        :return: dict with error status, codigo, vigencia, mensajes, raw response
        """
        if not config:
            return {"error": True, "mensajes": "No SIAT configuration provided", "raw": ""}

        if not cuis:
            return {"error": True, "mensajes": "CUIS is required for CUFD request", "raw": ""}

        url = (config.wsdl_codigos or '').strip()
        if url.endswith('?wsdl') or '?wsdl' in url:
            url = url.split('?wsdl')[0]

        token = config.token or ''

        body = f"""<soapenv:Envelope xmlns:soapenv="http://schemas.xmlsoap.org/soap/envelope/" xmlns:siat="https://siat.impuestos.gob.bo/">
  <soapenv:Header/>
  <soapenv:Body>
    <siat:cufd>
      <SolicitudCufd>
        <codigoAmbiente>{config.codigo_ambiente}</codigoAmbiente>
        <codigoModalidad>{config.modalidad}</codigoModalidad>
        <codigoPuntoVenta>{company.siat_codigo_punto_venta}</codigoPuntoVenta>
        <codigoSistema>{config.codigo_sistema or ''}</codigoSistema>
        <codigoSucursal>{company.siat_codigo_sucursal}</codigoSucursal>
        <cuis>{cuis}</cuis>
        <nit>{(company.vat or '').strip()}</nit>
      </SolicitudCufd>
    </siat:cufd>
  </soapenv:Body>
</soapenv:Envelope>"""

        headers = {
            "Content-Type": "text/xml;charset=UTF-8",
            "apikey": f"TokenApi {token}"
        }

        try:
            r = requests.post(url, data=body.encode('utf-8'), headers=headers, timeout=timeout)
        except Exception as e:
            _logger.exception("SIAT HTTP request exception for CUFD")
            return {
                "error": True,
                "mensajes": f"HTTP request exception: {e}",
                "raw": str(e),
                "http_status": None
            }

        # Handle HTTP errors
        if r.status_code >= 400:
            _logger.warning("SIAT returned HTTP %s for CUFD URL %s", r.status_code, url)
            fault_msg = self._extract_soap_fault(r.text)
            resp_msgs = self._extract_respuesta_cufd_messages(r.text)
            combined = "; ".join(x for x in (fault_msg, resp_msgs) if x)
            if combined:
                return {
                    "error": True,
                    "http_status": r.status_code,
                    "mensajes": f"SIAT error: {combined}",
                    "raw": r.text
                }
            return {
                "error": True,
                "http_status": r.status_code,
                "mensajes": f"SIAT returned HTTP {r.status_code}",
                "raw": r.text
            }

        # Parse XML response
        try:
            root = ET.fromstring(r.content)
        except Exception as e:
            _logger.exception("Failed parsing SIAT CUFD XML")
            return {
                "error": True,
                "http_status": r.status_code,
                "mensajes": f"Invalid XML response: {e}",
                "raw": r.text
            }

        ns = {'ns': 'https://siat.impuestos.gob.bo/'}
        res_node = root.find('.//ns:RespuestaCufd', ns) or root.find('.//RespuestaCufd')

        if res_node is None:
            fault_msg = self._extract_soap_fault(r.text)
            resp_msgs = self._extract_respuesta_cufd_messages(r.text)
            combined = "; ".join(x for x in (fault_msg, resp_msgs) if x)
            if combined:
                return {
                    "error": True,
                    "http_status": r.status_code,
                    "mensajes": f"SIAT response parsing issue: {combined}",
                    "raw": r.text
                }
            return {
                "error": True,
                "http_status": r.status_code,
                "mensajes": "RespuestaCufd not found",
                "raw": r.text
            }

        # Extract response fields
        codigo = res_node.findtext('ns:codigo', None, ns) or res_node.findtext('codigo')
        codigoControl = res_node.findtext('ns:codigoControl', None, ns) or res_node.findtext('codigoControl')
        direccion = res_node.findtext('ns:direccion', None, ns) or res_node.findtext('direccion')
        fecha = res_node.findtext('ns:fechaVigencia', None, ns) or res_node.findtext('fechaVigencia')

        msgs = []
        for m in res_node.findall('.//{https://siat.impuestos.gob.bo/}mensajesList') + res_node.findall(
                './/mensajesList'):
            desc = m.findtext('{https://siat.impuestos.gob.bo/}descripcion') or m.findtext('descripcion')
            if desc:
                msgs.append(desc.strip())

        mensajes_text = " | ".join(msgs) if msgs else ''

        if not codigo:
            combined = mensajes_text or self._extract_soap_fault(r.text) or r.text
            return {
                "error": True,
                "http_status": r.status_code,
                "mensajes": f"No 'codigo' in SIAT CUFD response. Details: {combined}",
                "raw": r.text
            }

        # Parse date
        parsed_fecha = None
        try:
            parsed_fecha = parser.parse(fecha).strftime("%Y-%m-%d %H:%M:%S") if fecha else None
        except Exception:
            parsed_fecha = fecha

        return {
            "error": False,
            "codigo": codigo,
            "codigoControl": codigoControl or '',
            "direccion": direccion or '',
            "vigencia": parsed_fecha,
            "mensajes": mensajes_text or '',
            "raw": r.text
        }

    def _extract_respuesta_cufd_messages(self, xml_text):
        """Extract messages from RespuestaCufd XML"""
        try:
            root = ET.fromstring(xml_text)
        except Exception:
            return None

        ns = {'ns': 'https://siat.impuestos.gob.bo/'}
        res = root.find('.//ns:RespuestaCufd', ns) or root.find('.//RespuestaCufd')

        if res is None:
            return None

        msgs = []
        for m in res.findall('.//{https://siat.impuestos.gob.bo/}mensajesList') + res.findall('.//mensajesList'):
            desc = m.findtext('{https://siat.impuestos.gob.bo/}descripcion') or m.findtext('descripcion')
            if desc:
                msgs.append(desc.strip())

        return " | ".join(msgs) if msgs else None

    def call_sincronizar_actividades(self, company, config, cuis, timeout=30):
        """
        Call SIAT sincronizarActividades web service

        :param company: res.company record
        :param config: alpha.siat.config record
        :param cuis: CUIS code string
        :param timeout: request timeout in seconds
        :return: dict with error status, activities list, mensajes, raw response
        """
        if not config:
            return {"error": True, "mensajes": "No SIAT configuration provided", "raw": ""}

        if not cuis:
            return {"error": True, "mensajes": "CUIS is required for sync request", "raw": ""}

        url = (config.wsdl_sync_url or '').strip()
        if url.endswith('?wsdl') or '?wsdl' in url:
            url = url.split('?wsdl')[0]

        token = config.token or ''

        body = f"""<soapenv:Envelope xmlns:soapenv="http://schemas.xmlsoap.org/soap/envelope/" xmlns:siat="https://siat.impuestos.gob.bo/">
  <soapenv:Header/>
  <soapenv:Body>
    <siat:sincronizarActividades>
      <SolicitudSincronizacion>
        <codigoAmbiente>{config.codigo_ambiente}</codigoAmbiente>
        <codigoPuntoVenta>{company.siat_codigo_punto_venta}</codigoPuntoVenta>
        <codigoSistema>{config.codigo_sistema or ''}</codigoSistema>
        <codigoSucursal>{company.siat_codigo_sucursal}</codigoSucursal>
        <cuis>{cuis}</cuis>
        <nit>{(company.vat or '').strip()}</nit>
      </SolicitudSincronizacion>
    </siat:sincronizarActividades>
  </soapenv:Body>
</soapenv:Envelope>"""

        headers = {
            "Content-Type": "text/xml;charset=UTF-8",
            "apikey": f"TokenApi {token}"
        }

        try:
            r = requests.post(url, data=body.encode('utf-8'), headers=headers, timeout=timeout)
        except Exception as e:
            _logger.exception("SIAT HTTP request exception for sincronizarActividades")
            return {
                "error": True,
                "mensajes": f"HTTP request exception: {e}",
                "raw": str(e),
                "http_status": None
            }

        # Handle HTTP errors
        if r.status_code >= 400:
            _logger.warning("SIAT returned HTTP %s for sync URL %s", r.status_code, url)
            fault_msg = self._extract_soap_fault(r.text)
            if fault_msg:
                return {
                    "error": True,
                    "http_status": r.status_code,
                    "mensajes": f"SIAT error: {fault_msg}",
                    "raw": r.text
                }
            return {
                "error": True,
                "http_status": r.status_code,
                "mensajes": f"SIAT returned HTTP {r.status_code}",
                "raw": r.text
            }

        # Parse XML response
        try:
            root = ET.fromstring(r.content)
        except Exception as e:
            _logger.exception("Failed parsing SIAT sincronizarActividades XML")
            return {
                "error": True,
                "http_status": r.status_code,
                "mensajes": f"Invalid XML response: {e}",
                "raw": r.text
            }

        ns = {'ns': 'https://siat.impuestos.gob.bo/'}
        res_node = root.find('.//ns:RespuestaListaActividades', ns) or root.find('.//RespuestaListaActividades')

        if res_node is None:
            fault_msg = self._extract_soap_fault(r.text)
            if fault_msg:
                return {
                    "error": True,
                    "http_status": r.status_code,
                    "mensajes": f"SIAT response parsing issue: {fault_msg}",
                    "raw": r.text
                }
            return {
                "error": True,
                "http_status": r.status_code,
                "mensajes": "RespuestaListaActividades not found",
                "raw": r.text
            }

        # Check transaction status
        transaccion = res_node.findtext('ns:transaccion', None, ns) or res_node.findtext('transaccion')
        if transaccion != 'true':
            # Extract messages if transaction failed
            msgs = []
            for m in res_node.findall('.//{https://siat.impuestos.gob.bo/}mensajesList') + res_node.findall(
                    './/mensajesList'):
                desc = m.findtext('{https://siat.impuestos.gob.bo/}descripcion') or m.findtext('descripcion')
                if desc:
                    msgs.append(desc.strip())
            mensajes_text = " | ".join(msgs) if msgs else 'Transaction failed'
            return {
                "error": True,
                "http_status": r.status_code,
                "mensajes": f"SIAT transaction failed: {mensajes_text}",
                "raw": r.text
            }

        # Extract activities list
        actividades = []
        for act_node in res_node.findall('.//ns:listaActividades', ns) + res_node.findall('.//listaActividades'):
            codigo = act_node.findtext('ns:codigoCaeb', None, ns) or act_node.findtext('codigoCaeb')
            desc = act_node.findtext('ns:descripcion', None, ns) or act_node.findtext('descripcion')
            tipo = act_node.findtext('ns:tipoActividad', None, ns) or act_node.findtext('tipoActividad')

            if codigo:
                actividades.append({
                    'codigoCaeb': codigo.strip(),
                    'descripcion': (desc or '').strip(),
                    'tipoActividad': (tipo or 'S').strip()
                })

        return {
            "error": False,
            "transaccion": True,
            "actividades": actividades,
            "mensajes": '',
            "raw": r.text
        }

    def call_sincronizar_actividades_documento_sector(self, company, config, cuis, timeout=30):
        """
        Call SIAT sincronizarListaActividadesDocumentoSector web service

        :param company: res.company record
        :param config: alpha.siat.config record
        :param cuis: CUIS code string
        :param timeout: request timeout in seconds
        :return: dict with error status, activities-document list, mensajes, raw response
        """
        if not config:
            return {"error": True, "mensajes": "No SIAT configuration provided", "raw": ""}

        if not cuis:
            return {"error": True, "mensajes": "CUIS is required for sync request", "raw": ""}

        url = (config.wsdl_sync_url or '').strip()
        if url.endswith('?wsdl') or '?wsdl' in url:
            url = url.split('?wsdl')[0]

        token = config.token or ''

        body = f"""<soapenv:Envelope xmlns:soapenv="http://schemas.xmlsoap.org/soap/envelope/" xmlns:siat="https://siat.impuestos.gob.bo/">
  <soapenv:Header/>
  <soapenv:Body>
    <siat:sincronizarListaActividadesDocumentoSector>
      <SolicitudSincronizacion>
        <codigoAmbiente>{config.codigo_ambiente}</codigoAmbiente>
        <codigoPuntoVenta>{company.siat_codigo_punto_venta}</codigoPuntoVenta>
        <codigoSistema>{config.codigo_sistema or ''}</codigoSistema>
        <codigoSucursal>{company.siat_codigo_sucursal}</codigoSucursal>
        <cuis>{cuis}</cuis>
        <nit>{(company.vat or '').strip()}</nit>
      </SolicitudSincronizacion>
    </siat:sincronizarListaActividadesDocumentoSector>
  </soapenv:Body>
</soapenv:Envelope>"""

        headers = {
            "Content-Type": "text/xml;charset=UTF-8",
            "apikey": f"TokenApi {token}"
        }

        try:
            r = requests.post(url, data=body.encode('utf-8'), headers=headers, timeout=timeout)
        except Exception as e:
            _logger.exception("SIAT HTTP request exception for sincronizarListaActividadesDocumentoSector")
            return {
                "error": True,
                "mensajes": f"HTTP request exception: {e}",
                "raw": str(e),
                "http_status": None
            }

        if r.status_code >= 400:
            _logger.warning("SIAT returned HTTP %s for sync URL %s", r.status_code, url)
            fault_msg = self._extract_soap_fault(r.text)
            if fault_msg:
                return {
                    "error": True,
                    "http_status": r.status_code,
                    "mensajes": f"SIAT error: {fault_msg}",
                    "raw": r.text
                }
            return {
                "error": True,
                "http_status": r.status_code,
                "mensajes": f"SIAT returned HTTP {r.status_code}",
                "raw": r.text
            }

        try:
            root = ET.fromstring(r.content)
        except Exception as e:
            _logger.exception("Failed parsing SIAT sincronizarListaActividadesDocumentoSector XML")
            return {
                "error": True,
                "http_status": r.status_code,
                "mensajes": f"Invalid XML response: {e}",
                "raw": r.text
            }

        ns = {'ns': 'https://siat.impuestos.gob.bo/'}
        res_node = root.find('.//ns:RespuestaListaActividadesDocumentoSector', ns) or \
                   root.find('.//RespuestaListaActividadesDocumentoSector')

        if res_node is None:
            fault_msg = self._extract_soap_fault(r.text)
            if fault_msg:
                return {
                    "error": True,
                    "http_status": r.status_code,
                    "mensajes": f"SIAT response parsing issue: {fault_msg}",
                    "raw": r.text
                }
            return {
                "error": True,
                "http_status": r.status_code,
                "mensajes": "RespuestaListaActividadesDocumentoSector not found",
                "raw": r.text
            }

        transaccion = res_node.findtext('ns:transaccion', None, ns) or res_node.findtext('transaccion')
        if transaccion != 'true':
            msgs = []
            for m in res_node.findall('.//{https://siat.impuestos.gob.bo/}mensajesList') + \
                     res_node.findall('.//mensajesList'):
                desc = m.findtext('{https://siat.impuestos.gob.bo/}descripcion') or m.findtext('descripcion')
                if desc:
                    msgs.append(desc.strip())
            mensajes_text = " | ".join(msgs) if msgs else 'Transaction failed'
            return {
                "error": True,
                "http_status": r.status_code,
                "mensajes": f"SIAT transaction failed: {mensajes_text}",
                "raw": r.text
            }

        # Extract activity-document list
        actividades_documentos = []
        for act_doc_node in res_node.findall('.//ns:listaActividadesDocumentoSector', ns) + \
                            res_node.findall('.//listaActividadesDocumentoSector'):
            codigo_act = act_doc_node.findtext('ns:codigoActividad', None, ns) or \
                         act_doc_node.findtext('codigoActividad')
            codigo_doc = act_doc_node.findtext('ns:codigoDocumentoSector', None, ns) or \
                         act_doc_node.findtext('codigoDocumentoSector')
            tipo_doc = act_doc_node.findtext('ns:tipoDocumentoSector', None, ns) or \
                       act_doc_node.findtext('tipoDocumentoSector')

            if codigo_act and codigo_doc:
                actividades_documentos.append({
                    'codigoActividad': codigo_act.strip(),
                    'codigoDocumentoSector': codigo_doc.strip(),
                    'tipoDocumentoSector': (tipo_doc or '').strip()
                })

        return {
            "error": False,
            "transaccion": True,
            "actividadesDocumentos": actividades_documentos,
            "mensajes": '',
            "raw": r.text
        }

    def call_sincronizar_mensajes_servicios(self, company, config, cuis, timeout=30):
        """
        Call SIAT sincronizarListaMensajesServicios web service

        :param company: res.company record
        :param config: alpha.siat.config record
        :param cuis: CUIS code string
        :param timeout: request timeout in seconds
        :return: dict with error status, messages list, mensajes, raw response
        """
        if not config:
            return {"error": True, "mensajes": "No SIAT configuration provided", "raw": ""}

        if not cuis:
            return {"error": True, "mensajes": "CUIS is required for sync request", "raw": ""}

        url = (config.wsdl_sync_url or '').strip()
        if url.endswith('?wsdl') or '?wsdl' in url:
            url = url.split('?wsdl')[0]

        token = config.token or ''

        body = f"""<soapenv:Envelope xmlns:soapenv="http://schemas.xmlsoap.org/soap/envelope/" xmlns:siat="https://siat.impuestos.gob.bo/">
  <soapenv:Header/>
  <soapenv:Body>
    <siat:sincronizarListaMensajesServicios>
      <SolicitudSincronizacion>
        <codigoAmbiente>{config.codigo_ambiente}</codigoAmbiente>
        <codigoPuntoVenta>{company.siat_codigo_punto_venta}</codigoPuntoVenta>
        <codigoSistema>{config.codigo_sistema or ''}</codigoSistema>
        <codigoSucursal>{company.siat_codigo_sucursal}</codigoSucursal>
        <cuis>{cuis}</cuis>
        <nit>{(company.vat or '').strip()}</nit>
      </SolicitudSincronizacion>
    </siat:sincronizarListaMensajesServicios>
  </soapenv:Body>
</soapenv:Envelope>"""

        headers = {
            "Content-Type": "text/xml;charset=UTF-8",
            "apikey": f"TokenApi {token}"
        }

        try:
            r = requests.post(url, data=body.encode('utf-8'), headers=headers, timeout=timeout)
        except Exception as e:
            _logger.exception("SIAT HTTP request exception for sincronizarListaMensajesServicios")
            return {
                "error": True,
                "mensajes": f"HTTP request exception: {e}",
                "raw": str(e),
                "http_status": None
            }

        if r.status_code >= 400:
            _logger.warning("SIAT returned HTTP %s for sync URL %s", r.status_code, url)
            fault_msg = self._extract_soap_fault(r.text)
            if fault_msg:
                return {
                    "error": True,
                    "http_status": r.status_code,
                    "mensajes": f"SIAT error: {fault_msg}",
                    "raw": r.text
                }
            return {
                "error": True,
                "http_status": r.status_code,
                "mensajes": f"SIAT returned HTTP {r.status_code}",
                "raw": r.text
            }

        try:
            root = ET.fromstring(r.content)
        except Exception as e:
            _logger.exception("Failed parsing SIAT sincronizarListaMensajesServicios XML")
            return {
                "error": True,
                "http_status": r.status_code,
                "mensajes": f"Invalid XML response: {e}",
                "raw": r.text
            }

        ns = {'ns': 'https://siat.impuestos.gob.bo/'}
        res_node = root.find('.//ns:RespuestaListaParametricas', ns) or \
                   root.find('.//RespuestaListaParametricas')

        if res_node is None:
            fault_msg = self._extract_soap_fault(r.text)
            if fault_msg:
                return {
                    "error": True,
                    "http_status": r.status_code,
                    "mensajes": f"SIAT response parsing issue: {fault_msg}",
                    "raw": r.text
                }
            return {
                "error": True,
                "http_status": r.status_code,
                "mensajes": "RespuestaListaParametricas not found",
                "raw": r.text
            }

        transaccion = res_node.findtext('ns:transaccion', None, ns) or res_node.findtext('transaccion')
        if transaccion != 'true':
            msgs = []
            for m in res_node.findall('.//{https://siat.impuestos.gob.bo/}mensajesList') + \
                     res_node.findall('.//mensajesList'):
                desc = m.findtext('{https://siat.impuestos.gob.bo/}descripcion') or m.findtext('descripcion')
                if desc:
                    msgs.append(desc.strip())
            mensajes_text = " | ".join(msgs) if msgs else 'Transaction failed'
            return {
                "error": True,
                "http_status": r.status_code,
                "mensajes": f"SIAT transaction failed: {mensajes_text}",
                "raw": r.text
            }

        # Extract messages list
        mensajes_servicios = []
        for msg_node in res_node.findall('.//ns:listaCodigos', ns) + \
                        res_node.findall('.//listaCodigos'):
            codigo = msg_node.findtext('ns:codigoClasificador', None, ns) or \
                     msg_node.findtext('codigoClasificador')
            desc = msg_node.findtext('ns:descripcion', None, ns) or \
                   msg_node.findtext('descripcion')

            if codigo:
                mensajes_servicios.append({
                    'codigoClasificador': codigo.strip(),
                    'descripcion': (desc or '').strip()
                })

        return {
            "error": False,
            "transaccion": True,
            "mensajesServicios": mensajes_servicios,
            "mensajes": '',
            "raw": r.text
        }

    def call_sincronizar_productos_servicios(self, company, config, cuis, timeout=60):
        """
        Call SIAT sincronizarListaProductosServicios web service

        :param company: res.company record
        :param config: alpha.siat.config record
        :param cuis: CUIS code string
        :param timeout: request timeout in seconds (60s for large responses)
        :return: dict with error status, products list, mensajes, raw response
        """
        if not config:
            return {"error": True, "mensajes": "No SIAT configuration provided", "raw": ""}

        if not cuis:
            return {"error": True, "mensajes": "CUIS is required for sync request", "raw": ""}

        url = (config.wsdl_sync_url or '').strip()
        if url.endswith('?wsdl') or '?wsdl' in url:
            url = url.split('?wsdl')[0]

        token = config.token or ''

        body = f"""<soapenv:Envelope xmlns:soapenv="http://schemas.xmlsoap.org/soap/envelope/" xmlns:siat="https://siat.impuestos.gob.bo/">
  <soapenv:Header/>
  <soapenv:Body>
    <siat:sincronizarListaProductosServicios>
      <SolicitudSincronizacion>
        <codigoAmbiente>{config.codigo_ambiente}</codigoAmbiente>
        <codigoPuntoVenta>{company.siat_codigo_punto_venta}</codigoPuntoVenta>
        <codigoSistema>{config.codigo_sistema or ''}</codigoSistema>
        <codigoSucursal>{company.siat_codigo_sucursal}</codigoSucursal>
        <cuis>{cuis}</cuis>
        <nit>{(company.vat or '').strip()}</nit>
      </SolicitudSincronizacion>
    </siat:sincronizarListaProductosServicios>
  </soapenv:Body>
</soapenv:Envelope>"""

        headers = {
            "Content-Type": "text/xml;charset=UTF-8",
            "apikey": f"TokenApi {token}"
        }

        try:
            r = requests.post(url, data=body.encode('utf-8'), headers=headers, timeout=timeout)
        except Exception as e:
            _logger.exception("SIAT HTTP request exception for sincronizarListaProductosServicios")
            return {
                "error": True,
                "mensajes": f"HTTP request exception: {e}",
                "raw": str(e),
                "http_status": None
            }

        if r.status_code >= 400:
            _logger.warning("SIAT returned HTTP %s for sync URL %s", r.status_code, url)
            fault_msg = self._extract_soap_fault(r.text)
            if fault_msg:
                return {
                    "error": True,
                    "http_status": r.status_code,
                    "mensajes": f"SIAT error: {fault_msg}",
                    "raw": r.text
                }
            return {
                "error": True,
                "http_status": r.status_code,
                "mensajes": f"SIAT returned HTTP {r.status_code}",
                "raw": r.text
            }

        try:
            root = ET.fromstring(r.content)
        except Exception as e:
            _logger.exception("Failed parsing SIAT sincronizarListaProductosServicios XML")
            return {
                "error": True,
                "http_status": r.status_code,
                "mensajes": f"Invalid XML response: {e}",
                "raw": r.text
            }

        ns = {'ns': 'https://siat.impuestos.gob.bo/'}
        res_node = root.find('.//ns:RespuestaListaProductos', ns) or \
                   root.find('.//RespuestaListaProductos')

        if res_node is None:
            fault_msg = self._extract_soap_fault(r.text)
            if fault_msg:
                return {
                    "error": True,
                    "http_status": r.status_code,
                    "mensajes": f"SIAT response parsing issue: {fault_msg}",
                    "raw": r.text
                }
            return {
                "error": True,
                "http_status": r.status_code,
                "mensajes": "RespuestaListaProductos not found",
                "raw": r.text
            }

        transaccion = res_node.findtext('ns:transaccion', None, ns) or res_node.findtext('transaccion')
        if transaccion != 'true':
            msgs = []
            for m in res_node.findall('.//{https://siat.impuestos.gob.bo/}mensajesList') + \
                     res_node.findall('.//mensajesList'):
                desc = m.findtext('{https://siat.impuestos.gob.bo/}descripcion') or m.findtext('descripcion')
                if desc:
                    msgs.append(desc.strip())
            mensajes_text = " | ".join(msgs) if msgs else 'Transaction failed'
            return {
                "error": True,
                "http_status": r.status_code,
                "mensajes": f"SIAT transaction failed: {mensajes_text}",
                "raw": r.text
            }

        # Extract products list
        productos = []
        for prod_node in res_node.findall('.//ns:listaCodigos', ns) + \
                         res_node.findall('.//listaCodigos'):
            codigo_act = prod_node.findtext('ns:codigoActividad', None, ns) or \
                         prod_node.findtext('codigoActividad')
            codigo_prod = prod_node.findtext('ns:codigoProducto', None, ns) or \
                          prod_node.findtext('codigoProducto')
            desc_prod = prod_node.findtext('ns:descripcionProducto', None, ns) or \
                        prod_node.findtext('descripcionProducto')

            if codigo_act and codigo_prod:
                # Extract NANDINA codes (can be multiple)
                nandinas = []
                for nandina_node in prod_node.findall('.//ns:nandina', ns) + \
                                    prod_node.findall('.//nandina'):
                    nandina_text = nandina_node.text
                    if nandina_text:
                        nandinas.append(nandina_text.strip())

                productos.append({
                    'codigoActividad': codigo_act.strip(),
                    'codigoProducto': codigo_prod.strip(),
                    'descripcionProducto': (desc_prod or '').strip(),
                    'nandinas': nandinas
                })

        return {
            "error": False,
            "transaccion": True,
            "productos": productos,
            "mensajes": '',
            "raw": r.text
        }

    def call_sincronizar_leyendas_factura(self, company, config, cuis, timeout=30):
        """
        Call SIAT sincronizarListaLeyendasFactura web service

        :param company: res.company record
        :param config: alpha.siat.config record
        :param cuis: CUIS code string
        :param timeout: request timeout in seconds
        :return: dict with error status, legends list, mensajes, raw response
        """
        if not config:
            return {"error": True, "mensajes": "No SIAT configuration provided", "raw": ""}

        if not cuis:
            return {"error": True, "mensajes": "CUIS is required for sync request", "raw": ""}

        url = (config.wsdl_sync_url or '').strip()
        if url.endswith('?wsdl') or '?wsdl' in url:
            url = url.split('?wsdl')[0]

        token = config.token or ''

        body = f"""<soapenv:Envelope xmlns:soapenv="http://schemas.xmlsoap.org/soap/envelope/" xmlns:siat="https://siat.impuestos.gob.bo/">
  <soapenv:Header/>
  <soapenv:Body>
    <siat:sincronizarListaLeyendasFactura>
      <SolicitudSincronizacion>
        <codigoAmbiente>{config.codigo_ambiente}</codigoAmbiente>
        <codigoPuntoVenta>{company.siat_codigo_punto_venta}</codigoPuntoVenta>
        <codigoSistema>{config.codigo_sistema or ''}</codigoSistema>
        <codigoSucursal>{company.siat_codigo_sucursal}</codigoSucursal>
        <cuis>{cuis}</cuis>
        <nit>{(company.vat or '').strip()}</nit>
      </SolicitudSincronizacion>
    </siat:sincronizarListaLeyendasFactura>
  </soapenv:Body>
</soapenv:Envelope>"""

        headers = {
            "Content-Type": "text/xml;charset=UTF-8",
            "apikey": f"TokenApi {token}"
        }

        try:
            r = requests.post(url, data=body.encode('utf-8'), headers=headers, timeout=timeout)
        except Exception as e:
            _logger.exception("SIAT HTTP request exception for sincronizarListaLeyendasFactura")
            return {
                "error": True,
                "mensajes": f"HTTP request exception: {e}",
                "raw": str(e),
                "http_status": None
            }

        if r.status_code >= 400:
            _logger.warning("SIAT returned HTTP %s for sync URL %s", r.status_code, url)
            fault_msg = self._extract_soap_fault(r.text)
            if fault_msg:
                return {
                    "error": True,
                    "http_status": r.status_code,
                    "mensajes": f"SIAT error: {fault_msg}",
                    "raw": r.text
                }
            return {
                "error": True,
                "http_status": r.status_code,
                "mensajes": f"SIAT returned HTTP {r.status_code}",
                "raw": r.text
            }

        try:
            root = ET.fromstring(r.content)
        except Exception as e:
            _logger.exception("Failed parsing SIAT sincronizarListaLeyendasFactura XML")
            return {
                "error": True,
                "http_status": r.status_code,
                "mensajes": f"Invalid XML response: {e}",
                "raw": r.text
            }

        ns = {'ns': 'https://siat.impuestos.gob.bo/'}
        res_node = root.find('.//ns:RespuestaListaParametricasLeyendas', ns) or \
                   root.find('.//RespuestaListaParametricasLeyendas')

        if res_node is None:
            fault_msg = self._extract_soap_fault(r.text)
            if fault_msg:
                return {
                    "error": True,
                    "http_status": r.status_code,
                    "mensajes": f"SIAT response parsing issue: {fault_msg}",
                    "raw": r.text
                }
            return {
                "error": True,
                "http_status": r.status_code,
                "mensajes": "RespuestaListaParametricasLeyendas not found",
                "raw": r.text
            }

        transaccion = res_node.findtext('ns:transaccion', None, ns) or res_node.findtext('transaccion')
        if transaccion != 'true':
            msgs = []
            for m in res_node.findall('.//{https://siat.impuestos.gob.bo/}mensajesList') + \
                     res_node.findall('.//mensajesList'):
                desc = m.findtext('{https://siat.impuestos.gob.bo/}descripcion') or m.findtext('descripcion')
                if desc:
                    msgs.append(desc.strip())
            mensajes_text = " | ".join(msgs) if msgs else 'Transaction failed'
            return {
                "error": True,
                "http_status": r.status_code,
                "mensajes": f"SIAT transaction failed: {mensajes_text}",
                "raw": r.text
            }

        # Extract legends list
        leyendas = []
        for ley_node in res_node.findall('.//ns:listaLeyendas', ns) + \
                        res_node.findall('.//listaLeyendas'):
            codigo_act = ley_node.findtext('ns:codigoActividad', None, ns) or \
                         ley_node.findtext('codigoActividad')
            desc_ley = ley_node.findtext('ns:descripcionLeyenda', None, ns) or \
                       ley_node.findtext('descripcionLeyenda')

            if codigo_act and desc_ley:
                leyendas.append({
                    'codigoActividad': codigo_act.strip(),
                    'descripcionLeyenda': desc_ley.strip()
                })

        return {
            "error": False,
            "transaccion": True,
            "leyendas": leyendas,
            "mensajes": '',
            "raw": r.text
        }

    def call_sincronizar_eventos_significativos(self, company, config, cuis, timeout=30):
        """
        Call SIAT sincronizarParametricaEventosSignificativos web service

        :param company: res.company record
        :param config: alpha.siat.config record
        :param cuis: CUIS code string
        :param timeout: request timeout in seconds
        :return: dict with error status, events list, mensajes, raw response
        """
        if not config:
            return {"error": True, "mensajes": "No SIAT configuration provided", "raw": ""}

        if not cuis:
            return {"error": True, "mensajes": "CUIS is required for sync request", "raw": ""}

        url = (config.wsdl_sync_url or '').strip()
        if url.endswith('?wsdl') or '?wsdl' in url:
            url = url.split('?wsdl')[0]

        token = config.token or ''

        body = f"""<soapenv:Envelope xmlns:soapenv="http://schemas.xmlsoap.org/soap/envelope/" xmlns:siat="https://siat.impuestos.gob.bo/">
  <soapenv:Header/>
  <soapenv:Body>
    <siat:sincronizarParametricaEventosSignificativos>
      <SolicitudSincronizacion>
        <codigoAmbiente>{config.codigo_ambiente}</codigoAmbiente>
        <codigoPuntoVenta>{company.siat_codigo_punto_venta}</codigoPuntoVenta>
        <codigoSistema>{config.codigo_sistema or ''}</codigoSistema>
        <codigoSucursal>{company.siat_codigo_sucursal}</codigoSucursal>
        <cuis>{cuis}</cuis>
        <nit>{(company.vat or '').strip()}</nit>
      </SolicitudSincronizacion>
    </siat:sincronizarParametricaEventosSignificativos>
  </soapenv:Body>
</soapenv:Envelope>"""

        headers = {
            "Content-Type": "text/xml;charset=UTF-8",
            "apikey": f"TokenApi {token}"
        }

        try:
            r = requests.post(url, data=body.encode('utf-8'), headers=headers, timeout=timeout)
        except Exception as e:
            _logger.exception("SIAT HTTP request exception for sincronizarParametricaEventosSignificativos")
            return {
                "error": True,
                "mensajes": f"HTTP request exception: {e}",
                "raw": str(e),
                "http_status": None
            }

        if r.status_code >= 400:
            _logger.warning("SIAT returned HTTP %s for sync URL %s", r.status_code, url)
            fault_msg = self._extract_soap_fault(r.text)
            if fault_msg:
                return {
                    "error": True,
                    "http_status": r.status_code,
                    "mensajes": f"SIAT error: {fault_msg}",
                    "raw": r.text
                }
            return {
                "error": True,
                "http_status": r.status_code,
                "mensajes": f"SIAT returned HTTP {r.status_code}",
                "raw": r.text
            }

        try:
            root = ET.fromstring(r.content)
        except Exception as e:
            _logger.exception("Failed parsing SIAT sincronizarParametricaEventosSignificativos XML")
            return {
                "error": True,
                "http_status": r.status_code,
                "mensajes": f"Invalid XML response: {e}",
                "raw": r.text
            }

        ns = {'ns': 'https://siat.impuestos.gob.bo/'}
        res_node = root.find('.//ns:RespuestaListaParametricas', ns) or \
                   root.find('.//RespuestaListaParametricas')

        if res_node is None:
            fault_msg = self._extract_soap_fault(r.text)
            if fault_msg:
                return {
                    "error": True,
                    "http_status": r.status_code,
                    "mensajes": f"SIAT response parsing issue: {fault_msg}",
                    "raw": r.text
                }
            return {
                "error": True,
                "http_status": r.status_code,
                "mensajes": "RespuestaListaParametricas not found",
                "raw": r.text
            }

        transaccion = res_node.findtext('ns:transaccion', None, ns) or res_node.findtext('transaccion')
        if transaccion != 'true':
            msgs = []
            for m in res_node.findall('.//{https://siat.impuestos.gob.bo/}mensajesList') + \
                     res_node.findall('.//mensajesList'):
                desc = m.findtext('{https://siat.impuestos.gob.bo/}descripcion') or m.findtext('descripcion')
                if desc:
                    msgs.append(desc.strip())
            mensajes_text = " | ".join(msgs) if msgs else 'Transaction failed'
            return {
                "error": True,
                "http_status": r.status_code,
                "mensajes": f"SIAT transaction failed: {mensajes_text}",
                "raw": r.text
            }

        # Extract events list
        eventos = []
        for evento_node in res_node.findall('.//ns:listaCodigos', ns) + \
                           res_node.findall('.//listaCodigos'):
            codigo = evento_node.findtext('ns:codigoClasificador', None, ns) or \
                     evento_node.findtext('codigoClasificador')
            desc = evento_node.findtext('ns:descripcion', None, ns) or \
                   evento_node.findtext('descripcion')

            if codigo:
                eventos.append({
                    'codigoClasificador': codigo.strip(),
                    'descripcion': (desc or '').strip()
                })

        return {
            "error": False,
            "transaccion": True,
            "eventos": eventos,
            "mensajes": '',
            "raw": r.text
        }

    def call_sincronizar_motivos_anulacion(self, company, config, cuis, timeout=30):
        """
        Call SIAT sincronizarParametricaMotivoAnulacion web service

        :param company: res.company record
        :param config: alpha.siat.config record
        :param cuis: CUIS code string
        :param timeout: request timeout in seconds
        :return: dict with error status, reasons list, mensajes, raw response
        """
        if not config:
            return {"error": True, "mensajes": "No SIAT configuration provided", "raw": ""}

        if not cuis:
            return {"error": True, "mensajes": "CUIS is required for sync request", "raw": ""}

        url = (config.wsdl_sync_url or '').strip()
        if url.endswith('?wsdl') or '?wsdl' in url:
            url = url.split('?wsdl')[0]

        token = config.token or ''

        body = f"""<soapenv:Envelope xmlns:soapenv="http://schemas.xmlsoap.org/soap/envelope/" xmlns:siat="https://siat.impuestos.gob.bo/">
  <soapenv:Header/>
  <soapenv:Body>
    <siat:sincronizarParametricaMotivoAnulacion>
      <SolicitudSincronizacion>
        <codigoAmbiente>{config.codigo_ambiente}</codigoAmbiente>
        <codigoPuntoVenta>{company.siat_codigo_punto_venta}</codigoPuntoVenta>
        <codigoSistema>{config.codigo_sistema or ''}</codigoSistema>
        <codigoSucursal>{company.siat_codigo_sucursal}</codigoSucursal>
        <cuis>{cuis}</cuis>
        <nit>{(company.vat or '').strip()}</nit>
      </SolicitudSincronizacion>
    </siat:sincronizarParametricaMotivoAnulacion>
  </soapenv:Body>
</soapenv:Envelope>"""

        headers = {
            "Content-Type": "text/xml;charset=UTF-8",
            "apikey": f"TokenApi {token}"
        }

        try:
            r = requests.post(url, data=body.encode('utf-8'), headers=headers, timeout=timeout)
        except Exception as e:
            _logger.exception("SIAT HTTP request exception for sincronizarParametricaMotivoAnulacion")
            return {
                "error": True,
                "mensajes": f"HTTP request exception: {e}",
                "raw": str(e),
                "http_status": None
            }

        if r.status_code >= 400:
            _logger.warning("SIAT returned HTTP %s for sync URL %s", r.status_code, url)
            fault_msg = self._extract_soap_fault(r.text)
            if fault_msg:
                return {
                    "error": True,
                    "http_status": r.status_code,
                    "mensajes": f"SIAT error: {fault_msg}",
                    "raw": r.text
                }
            return {
                "error": True,
                "http_status": r.status_code,
                "mensajes": f"SIAT returned HTTP {r.status_code}",
                "raw": r.text
            }

        try:
            root = ET.fromstring(r.content)
        except Exception as e:
            _logger.exception("Failed parsing SIAT sincronizarParametricaMotivoAnulacion XML")
            return {
                "error": True,
                "http_status": r.status_code,
                "mensajes": f"Invalid XML response: {e}",
                "raw": r.text
            }

        ns = {'ns': 'https://siat.impuestos.gob.bo/'}
        res_node = root.find('.//ns:RespuestaListaParametricas', ns) or \
                   root.find('.//RespuestaListaParametricas')

        if res_node is None:
            fault_msg = self._extract_soap_fault(r.text)
            if fault_msg:
                return {
                    "error": True,
                    "http_status": r.status_code,
                    "mensajes": f"SIAT response parsing issue: {fault_msg}",
                    "raw": r.text
                }
            return {
                "error": True,
                "http_status": r.status_code,
                "mensajes": "RespuestaListaParametricas not found",
                "raw": r.text
            }

        transaccion = res_node.findtext('ns:transaccion', None, ns) or res_node.findtext('transaccion')
        if transaccion != 'true':
            msgs = []
            for m in res_node.findall('.//{https://siat.impuestos.gob.bo/}mensajesList') + \
                     res_node.findall('.//mensajesList'):
                desc = m.findtext('{https://siat.impuestos.gob.bo/}descripcion') or m.findtext('descripcion')
                if desc:
                    msgs.append(desc.strip())
            mensajes_text = " | ".join(msgs) if msgs else 'Transaction failed'
            return {
                "error": True,
                "http_status": r.status_code,
                "mensajes": f"SIAT transaction failed: {mensajes_text}",
                "raw": r.text
            }

        # Extract reasons list
        motivos = []
        for motivo_node in res_node.findall('.//ns:listaCodigos', ns) + \
                           res_node.findall('.//listaCodigos'):
            codigo = motivo_node.findtext('ns:codigoClasificador', None, ns) or \
                     motivo_node.findtext('codigoClasificador')
            desc = motivo_node.findtext('ns:descripcion', None, ns) or \
                   motivo_node.findtext('descripcion')

            if codigo:
                motivos.append({
                    'codigoClasificador': codigo.strip(),
                    'descripcion': (desc or '').strip()
                })

        return {
            "error": False,
            "transaccion": True,
            "motivos": motivos,
            "mensajes": '',
            "raw": r.text
        }

    def call_sincronizar_paises_origen(self, company, config, cuis, timeout=30):
        """
        Call SIAT sincronizarParametricaPaisOrigen web service

        :param company: res.company record
        :param config: alpha.siat.config record
        :param cuis: CUIS code string
        :param timeout: request timeout in seconds
        :return: dict with error status, countries list, mensajes, raw response
        """
        if not config:
            return {"error": True, "mensajes": "No SIAT configuration provided", "raw": ""}

        if not cuis:
            return {"error": True, "mensajes": "CUIS is required for sync request", "raw": ""}

        url = (config.wsdl_sync_url or '').strip()
        if url.endswith('?wsdl') or '?wsdl' in url:
            url = url.split('?wsdl')[0]

        token = config.token or ''

        body = f"""<soapenv:Envelope xmlns:soapenv="http://schemas.xmlsoap.org/soap/envelope/" xmlns:siat="https://siat.impuestos.gob.bo/">
  <soapenv:Header/>
  <soapenv:Body>
    <siat:sincronizarParametricaPaisOrigen>
      <SolicitudSincronizacion>
        <codigoAmbiente>{config.codigo_ambiente}</codigoAmbiente>
        <codigoPuntoVenta>{company.siat_codigo_punto_venta}</codigoPuntoVenta>
        <codigoSistema>{config.codigo_sistema or ''}</codigoSistema>
        <codigoSucursal>{company.siat_codigo_sucursal}</codigoSucursal>
        <cuis>{cuis}</cuis>
        <nit>{(company.vat or '').strip()}</nit>
      </SolicitudSincronizacion>
    </siat:sincronizarParametricaPaisOrigen>
  </soapenv:Body>
</soapenv:Envelope>"""

        headers = {
            "Content-Type": "text/xml;charset=UTF-8",
            "apikey": f"TokenApi {token}"
        }

        try:
            r = requests.post(url, data=body.encode('utf-8'), headers=headers, timeout=timeout)
        except Exception as e:
            _logger.exception("SIAT HTTP request exception for sincronizarParametricaPaisOrigen")
            return {
                "error": True,
                "mensajes": f"HTTP request exception: {e}",
                "raw": str(e),
                "http_status": None
            }

        if r.status_code >= 400:
            _logger.warning("SIAT returned HTTP %s for sync URL %s", r.status_code, url)
            fault_msg = self._extract_soap_fault(r.text)
            if fault_msg:
                return {
                    "error": True,
                    "http_status": r.status_code,
                    "mensajes": f"SIAT error: {fault_msg}",
                    "raw": r.text
                }
            return {
                "error": True,
                "http_status": r.status_code,
                "mensajes": f"SIAT returned HTTP {r.status_code}",
                "raw": r.text
            }

        try:
            root = ET.fromstring(r.content)
        except Exception as e:
            _logger.exception("Failed parsing SIAT sincronizarParametricaPaisOrigen XML")
            return {
                "error": True,
                "http_status": r.status_code,
                "mensajes": f"Invalid XML response: {e}",
                "raw": r.text
            }

        ns = {'ns': 'https://siat.impuestos.gob.bo/'}
        res_node = root.find('.//ns:RespuestaListaParametricas', ns) or \
                   root.find('.//RespuestaListaParametricas')

        if res_node is None:
            fault_msg = self._extract_soap_fault(r.text)
            if fault_msg:
                return {
                    "error": True,
                    "http_status": r.status_code,
                    "mensajes": f"SIAT response parsing issue: {fault_msg}",
                    "raw": r.text
                }
            return {
                "error": True,
                "http_status": r.status_code,
                "mensajes": "RespuestaListaParametricas not found",
                "raw": r.text
            }

        transaccion = res_node.findtext('ns:transaccion', None, ns) or res_node.findtext('transaccion')
        if transaccion != 'true':
            msgs = []
            for m in res_node.findall('.//{https://siat.impuestos.gob.bo/}mensajesList') + \
                     res_node.findall('.//mensajesList'):
                desc = m.findtext('{https://siat.impuestos.gob.bo/}descripcion') or m.findtext('descripcion')
                if desc:
                    msgs.append(desc.strip())
            mensajes_text = " | ".join(msgs) if msgs else 'Transaction failed'
            return {
                "error": True,
                "http_status": r.status_code,
                "mensajes": f"SIAT transaction failed: {mensajes_text}",
                "raw": r.text
            }

        # Extract countries list
        paises = []
        for pais_node in res_node.findall('.//ns:listaCodigos', ns) + \
                         res_node.findall('.//listaCodigos'):
            codigo = pais_node.findtext('ns:codigoClasificador', None, ns) or \
                     pais_node.findtext('codigoClasificador')
            desc = pais_node.findtext('ns:descripcion', None, ns) or \
                   pais_node.findtext('descripcion')

            if codigo:
                paises.append({
                    'codigoClasificador': codigo.strip(),
                    'descripcion': (desc or '').strip()
                })

        return {
            "error": False,
            "transaccion": True,
            "paises": paises,
            "mensajes": '',
            "raw": r.text
        }

    def call_sincronizar_tipos_documento_identidad(self, company, config, cuis, timeout=30):
        """
        Call SIAT sincronizarParametricaTipoDocumentoIdentidad web service

        :param company: res.company record
        :param config: alpha.siat.config record
        :param cuis: CUIS code string
        :param timeout: request timeout in seconds
        :return: dict with error status, document types list, mensajes, raw response
        """
        if not config:
            return {"error": True, "mensajes": "No SIAT configuration provided", "raw": ""}

        if not cuis:
            return {"error": True, "mensajes": "CUIS is required for sync request", "raw": ""}

        url = (config.wsdl_sync_url or '').strip()
        if url.endswith('?wsdl') or '?wsdl' in url:
            url = url.split('?wsdl')[0]

        token = config.token or ''

        body = f"""<soapenv:Envelope xmlns:soapenv="http://schemas.xmlsoap.org/soap/envelope/" xmlns:siat="https://siat.impuestos.gob.bo/">
  <soapenv:Header/>
  <soapenv:Body>
    <siat:sincronizarParametricaTipoDocumentoIdentidad>
      <SolicitudSincronizacion>
        <codigoAmbiente>{config.codigo_ambiente}</codigoAmbiente>
        <codigoPuntoVenta>{company.siat_codigo_punto_venta}</codigoPuntoVenta>
        <codigoSistema>{config.codigo_sistema or ''}</codigoSistema>
        <codigoSucursal>{company.siat_codigo_sucursal}</codigoSucursal>
        <cuis>{cuis}</cuis>
        <nit>{(company.vat or '').strip()}</nit>
      </SolicitudSincronizacion>
    </siat:sincronizarParametricaTipoDocumentoIdentidad>
  </soapenv:Body>
</soapenv:Envelope>"""

        headers = {
            "Content-Type": "text/xml;charset=UTF-8",
            "apikey": f"TokenApi {token}"
        }

        try:
            r = requests.post(url, data=body.encode('utf-8'), headers=headers, timeout=timeout)
        except Exception as e:
            _logger.exception("SIAT HTTP request exception for sincronizarParametricaTipoDocumentoIdentidad")
            return {
                "error": True,
                "mensajes": f"HTTP request exception: {e}",
                "raw": str(e),
                "http_status": None
            }

        if r.status_code >= 400:
            _logger.warning("SIAT returned HTTP %s for sync URL %s", r.status_code, url)
            fault_msg = self._extract_soap_fault(r.text)
            if fault_msg:
                return {
                    "error": True,
                    "http_status": r.status_code,
                    "mensajes": f"SIAT error: {fault_msg}",
                    "raw": r.text
                }
            return {
                "error": True,
                "http_status": r.status_code,
                "mensajes": f"SIAT returned HTTP {r.status_code}",
                "raw": r.text
            }

        try:
            root = ET.fromstring(r.content)
        except Exception as e:
            _logger.exception("Failed parsing SIAT sincronizarParametricaTipoDocumentoIdentidad XML")
            return {
                "error": True,
                "http_status": r.status_code,
                "mensajes": f"Invalid XML response: {e}",
                "raw": r.text
            }

        ns = {'ns': 'https://siat.impuestos.gob.bo/'}
        res_node = root.find('.//ns:RespuestaListaParametricas', ns) or \
                   root.find('.//RespuestaListaParametricas')

        if res_node is None:
            fault_msg = self._extract_soap_fault(r.text)
            if fault_msg:
                return {
                    "error": True,
                    "http_status": r.status_code,
                    "mensajes": f"SIAT response parsing issue: {fault_msg}",
                    "raw": r.text
                }
            return {
                "error": True,
                "http_status": r.status_code,
                "mensajes": "RespuestaListaParametricas not found",
                "raw": r.text
            }

        transaccion = res_node.findtext('ns:transaccion', None, ns) or res_node.findtext('transaccion')
        if transaccion != 'true':
            msgs = []
            for m in res_node.findall('.//{https://siat.impuestos.gob.bo/}mensajesList') + \
                     res_node.findall('.//mensajesList'):
                desc = m.findtext('{https://siat.impuestos.gob.bo/}descripcion') or m.findtext('descripcion')
                if desc:
                    msgs.append(desc.strip())
            mensajes_text = " | ".join(msgs) if msgs else 'Transaction failed'
            return {
                "error": True,
                "http_status": r.status_code,
                "mensajes": f"SIAT transaction failed: {mensajes_text}",
                "raw": r.text
            }

        # Extract document types list
        tipos = []
        for tipo_node in res_node.findall('.//ns:listaCodigos', ns) + \
                         res_node.findall('.//listaCodigos'):
            codigo = tipo_node.findtext('ns:codigoClasificador', None, ns) or \
                     tipo_node.findtext('codigoClasificador')
            desc = tipo_node.findtext('ns:descripcion', None, ns) or \
                   tipo_node.findtext('descripcion')

            if codigo:
                tipos.append({
                    'codigoClasificador': codigo.strip(),
                    'descripcion': (desc or '').strip()
                })

        return {
            "error": False,
            "transaccion": True,
            "tipos": tipos,
            "mensajes": '',
            "raw": r.text
        }

    def call_sincronizar_tipos_habitacion(self, company, config, cuis, timeout=30):
        """
        Call SIAT sincronizarParametricaTipoHabitacion web service
        Returns dict similar to other sync calls: {'error': False, 'transaccion': True, 'tipos': [...]}
        """
        if not config:
            return {"error": True, "mensajes": "No SIAT configuration provided", "raw": ""}

        if not cuis:
            return {"error": True, "mensajes": "CUIS is required for sync request", "raw": ""}

        url = (config.wsdl_sync_url or '').strip()
        if url.endswith('?wsdl') or '?wsdl' in url:
            url = url.split('?wsdl')[0]

        token = config.token or ''

        body = f"""<soapenv:Envelope xmlns:soapenv="http://schemas.xmlsoap.org/soap/envelope/" xmlns:siat="https://siat.impuestos.gob.bo/">
  <soapenv:Header/>
  <soapenv:Body>
    <siat:sincronizarParametricaTipoHabitacion>
      <SolicitudSincronizacion>
        <codigoAmbiente>{config.codigo_ambiente}</codigoAmbiente>
        <codigoPuntoVenta>{company.siat_codigo_punto_venta}</codigoPuntoVenta>
        <codigoSistema>{config.codigo_sistema or ''}</codigoSistema>
        <codigoSucursal>{company.siat_codigo_sucursal}</codigoSucursal>
        <cuis>{cuis}</cuis>
        <nit>{(company.vat or '').strip()}</nit>
      </SolicitudSincronizacion>
    </siat:sincronizarParametricaTipoHabitacion>
  </soapenv:Body>
</soapenv:Envelope>"""

        headers = {
            "Content-Type": "text/xml;charset=UTF-8",
            "apikey": f"TokenApi {token}"
        }

        try:
            r = requests.post(url, data=body.encode('utf-8'), headers=headers, timeout=timeout)
        except Exception as e:
            _logger.exception("SIAT HTTP request exception for sincronizarParametricaTipoHabitacion")
            return {"error": True, "mensajes": f"HTTP request exception: {e}", "raw": str(e), "http_status": None}

        if r.status_code >= 400:
            _logger.warning("SIAT returned HTTP %s for sync URL %s", r.status_code, url)
            fault_msg = self._extract_soap_fault(r.text)
            if fault_msg:
                return {"error": True, "http_status": r.status_code, "mensajes": f"SIAT error: {fault_msg}", "raw": r.text}
            return {"error": True, "http_status": r.status_code, "mensajes": f"SIAT returned HTTP {r.status_code}", "raw": r.text}

        try:
            root = ET.fromstring(r.content)
        except Exception as e:
            _logger.exception("Failed parsing SIAT sincronizarParametricaTipoHabitacion XML")
            return {"error": True, "http_status": r.status_code, "mensajes": f"Invalid XML response: {e}", "raw": r.text}

        ns = {'ns': 'https://siat.impuestos.gob.bo/'}
        res_node = root.find('.//ns:RespuestaListaParametricas', ns) or root.find('.//RespuestaListaParametricas')
        if res_node is None:
            fault_msg = self._extract_soap_fault(r.text)
            if fault_msg:
                return {"error": True, "http_status": r.status_code, "mensajes": f"SIAT response parsing issue: {fault_msg}", "raw": r.text}
            return {"error": True, "http_status": r.status_code, "mensajes": "RespuestaListaParametricas not found", "raw": r.text}

        transaccion = res_node.findtext('ns:transaccion', None, ns) or res_node.findtext('transaccion')
        if transaccion != 'true':
            msgs = []
            for m in res_node.findall('.//{https://siat.impuestos.gob.bo/}mensajesList') + res_node.findall('.//mensajesList'):
                desc = m.findtext('{https://siat.impuestos.gob.bo/}descripcion') or m.findtext('descripcion')
                if desc:
                    msgs.append(desc.strip())
            mensajes_text = " | ".join(msgs) if msgs else 'Transaction failed'
            return {"error": True, "http_status": r.status_code, "mensajes": f"SIAT transaction failed: {mensajes_text}", "raw": r.text}

        tipos = []
        for tipo_node in res_node.findall('.//ns:listaCodigos', ns) + res_node.findall('.//listaCodigos'):
            codigo = tipo_node.findtext('ns:codigoClasificador', None, ns) or tipo_node.findtext('codigoClasificador')
            desc = tipo_node.findtext('ns:descripcion', None, ns) or tipo_node.findtext('descripcion')
            if codigo:
                tipos.append({
                    'codigoClasificador': codigo.strip(),
                    'descripcion': (desc or '').strip()
                })

        return {"error": False, "transaccion": True, "tipos": tipos, "mensajes": '', "raw": r.text}

    def call_sincronizar_tipos_metodo_pago(self, company, config, cuis, timeout=30):
        """
        Call SIAT sincronizarParametricaTipoMetodoPago web service.
        Returns dict: { error: bool, transaccion: bool, tipos: [ {codigoClasificador, descripcion} ], mensajes, raw }
        """
        if not config:
            return {"error": True, "mensajes": "No SIAT configuration provided", "raw": ""}

        if not cuis:
            return {"error": True, "mensajes": "CUIS is required for sync request", "raw": ""}

        url = (config.wsdl_sync_url or '').strip()
        if url.endswith('?wsdl') or '?wsdl' in url:
            url = url.split('?wsdl')[0]

        token = config.token or ''

        body = f"""<soapenv:Envelope xmlns:soapenv="http://schemas.xmlsoap.org/soap/envelope/" xmlns:siat="https://siat.impuestos.gob.bo/">
  <soapenv:Header/>
  <soapenv:Body>
    <siat:sincronizarParametricaTipoMetodoPago>
      <SolicitudSincronizacion>
        <codigoAmbiente>{config.codigo_ambiente}</codigoAmbiente>
        <codigoPuntoVenta>{company.siat_codigo_punto_venta}</codigoPuntoVenta>
        <codigoSistema>{config.codigo_sistema or ''}</codigoSistema>
        <codigoSucursal>{company.siat_codigo_sucursal}</codigoSucursal>
        <cuis>{cuis}</cuis>
        <nit>{(company.vat or '').strip()}</nit>
      </SolicitudSincronizacion>
    </siat:sincronizarParametricaTipoMetodoPago>
  </soapenv:Body>
</soapenv:Envelope>"""

        headers = {
            "Content-Type": "text/xml;charset=UTF-8",
            "apikey": f"TokenApi {token}"
        }

        try:
            r = requests.post(url, data=body.encode('utf-8'), headers=headers, timeout=timeout)
        except Exception as e:
            _logger.exception("SIAT HTTP request exception for sincronizarParametricaTipoMetodoPago")
            return {"error": True, "mensajes": f"HTTP request exception: {e}", "raw": str(e), "http_status": None}

        if r.status_code >= 400:
            _logger.warning("SIAT returned HTTP %s for sync URL %s", r.status_code, url)
            fault_msg = self._extract_soap_fault(r.text)
            if fault_msg:
                return {"error": True, "http_status": r.status_code, "mensajes": f"SIAT error: {fault_msg}", "raw": r.text}
            return {"error": True, "http_status": r.status_code, "mensajes": f"SIAT returned HTTP {r.status_code}", "raw": r.text}

        try:
            root = ET.fromstring(r.content)
        except Exception as e:
            _logger.exception("Failed parsing SIAT sincronizarParametricaTipoMetodoPago XML")
            return {"error": True, "http_status": r.status_code, "mensajes": f"Invalid XML response: {e}", "raw": r.text}

        ns = {'ns': 'https://siat.impuestos.gob.bo/'}
        res_node = root.find('.//ns:RespuestaListaParametricas', ns) or root.find('.//RespuestaListaParametricas')
        if res_node is None:
            fault_msg = self._extract_soap_fault(r.text)
            if fault_msg:
                return {"error": True, "http_status": r.status_code, "mensajes": f"SIAT response parsing issue: {fault_msg}", "raw": r.text}
            return {"error": True, "http_status": r.status_code, "mensajes": "RespuestaListaParametricas not found", "raw": r.text}

        transaccion = res_node.findtext('ns:transaccion', None, ns) or res_node.findtext('transaccion')
        if transaccion != 'true':
            msgs = []
            for m in res_node.findall('.//{https://siat.impuestos.gob.bo/}mensajesList') + res_node.findall('.//mensajesList'):
                desc = m.findtext('{https://siat.impuestos.gob.bo/}descripcion') or m.findtext('descripcion')
                if desc:
                    msgs.append(desc.strip())
            mensajes_text = " | ".join(msgs) if msgs else 'Transaction failed'
            return {"error": True, "http_status": r.status_code, "mensajes": f"SIAT transaction failed: {mensajes_text}", "raw": r.text}

        tipos = []
        for tipo_node in res_node.findall('.//ns:listaCodigos', ns) + res_node.findall('.//listaCodigos'):
            codigo = tipo_node.findtext('ns:codigoClasificador', None, ns) or tipo_node.findtext('codigoClasificador')
            desc = tipo_node.findtext('ns:descripcion', None, ns) or tipo_node.findtext('descripcion')
            if codigo:
                tipos.append({
                    'codigoClasificador': codigo.strip(),
                    'descripcion': (desc or '').strip()
                })

        return {"error": False, "transaccion": True, "tipos": tipos, "mensajes": '', "raw": r.text}

    def call_sincronizar_tipos_moneda(self, company, config, cuis, timeout=30):
        """
        Call SIAT sincronizarParametricaTipoMoneda web service.
        Returns dict: { error, transaccion, tipos, mensajes, raw }
        """
        if not config:
            return {"error": True, "mensajes": "No SIAT configuration provided", "raw": ""}

        if not cuis:
            return {"error": True, "mensajes": "CUIS is required for sync request", "raw": ""}

        url = (config.wsdl_sync_url or '').strip()
        if url.endswith('?wsdl') or '?wsdl' in url:
            url = url.split('?wsdl')[0]

        token = config.token or ''

        body = f"""<soapenv:Envelope xmlns:soapenv="http://schemas.xmlsoap.org/soap/envelope/" xmlns:siat="https://siat.impuestos.gob.bo/">
  <soapenv:Header/>
  <soapenv:Body>
    <siat:sincronizarParametricaTipoMoneda>
      <SolicitudSincronizacion>
        <codigoAmbiente>{config.codigo_ambiente}</codigoAmbiente>
        <codigoPuntoVenta>{company.siat_codigo_punto_venta}</codigoPuntoVenta>
        <codigoSistema>{config.codigo_sistema or ''}</codigoSistema>
        <codigoSucursal>{company.siat_codigo_sucursal}</codigoSucursal>
        <cuis>{cuis}</cuis>
        <nit>{(company.vat or '').strip()}</nit>
      </SolicitudSincronizacion>
    </siat:sincronizarParametricaTipoMoneda>
  </soapenv:Body>
</soapenv:Envelope>"""

        headers = {"Content-Type": "text/xml;charset=UTF-8", "apikey": f"TokenApi {token}"}

        try:
            r = requests.post(url, data=body.encode('utf-8'), headers=headers, timeout=timeout)
        except Exception as e:
            _logger.exception("SIAT HTTP request exception for sincronizarParametricaTipoMoneda")
            return {"error": True, "mensajes": f"HTTP request exception: {e}", "raw": str(e), "http_status": None}

        if r.status_code >= 400:
            _logger.warning("SIAT returned HTTP %s for sync URL %s", r.status_code, url)
            fault_msg = self._extract_soap_fault(r.text)
            if fault_msg:
                return {"error": True, "http_status": r.status_code, "mensajes": f"SIAT error: {fault_msg}", "raw": r.text}
            return {"error": True, "http_status": r.status_code, "mensajes": f"SIAT returned HTTP {r.status_code}", "raw": r.text}

        try:
            root = ET.fromstring(r.content)
        except Exception as e:
            _logger.exception("Failed parsing SIAT sincronizarParametricaTipoMoneda XML")
            return {"error": True, "http_status": r.status_code if 'r' in locals() else None, "mensajes": f"Invalid XML response: {e}", "raw": getattr(r, 'text', '')}

        ns = {'ns': 'https://siat.impuestos.gob.bo/'}
        res_node = root.find('.//ns:RespuestaListaParametricas', ns) or root.find('.//RespuestaListaParametricas')
        if res_node is None:
            fault_msg = self._extract_soap_fault(getattr(r, 'text', ''))
            if fault_msg:
                return {"error": True, "http_status": getattr(r, 'status_code', None), "mensajes": f"SIAT response parsing issue: {fault_msg}", "raw": getattr(r, 'text', '')}
            return {"error": True, "http_status": getattr(r, 'status_code', None), "mensajes": "RespuestaListaParametricas not found", "raw": getattr(r, 'text', '')}

        transaccion = res_node.findtext('ns:transaccion', None, ns) or res_node.findtext('transaccion')
        if transaccion != 'true':
            msgs = []
            for m in res_node.findall('.//{https://siat.impuestos.gob.bo/}mensajesList') + res_node.findall('.//mensajesList'):
                desc = m.findtext('{https://siat.impuestos.gob.bo/}descripcion') or m.findtext('descripcion')
                if desc:
                    msgs.append(desc.strip())
            mensajes_text = " | ".join(msgs) if msgs else 'Transaction failed'
            return {"error": True, "http_status": getattr(r, 'status_code', None), "mensajes": f"SIAT transaction failed: {mensajes_text}", "raw": getattr(r, 'text', '')}

        tipos = []
        for tipo_node in res_node.findall('.//ns:listaCodigos', ns) + res_node.findall('.//listaCodigos'):
            codigo = tipo_node.findtext('ns:codigoClasificador', None, ns) or tipo_node.findtext('codigoClasificador')
            desc = tipo_node.findtext('ns:descripcion', None, ns) or tipo_node.findtext('descripcion')
            if codigo:
                tipos.append({'codigoClasificador': codigo.strip(), 'descripcion': (desc or '').strip()})

        return {"error": False, "transaccion": True, "tipos": tipos, "mensajes": '', "raw": getattr(r, 'text', '')}

    def call_sincronizar_tipos_punto_venta(self, company, config, cuis, timeout=30):
        """
        Call SIAT sincronizarParametricaTipoPuntoVenta web service.
        Returns dict: { error, transaccion, tipos, mensajes, raw }
        """
        if not config:
            return {"error": True, "mensajes": "No SIAT configuration provided", "raw": ""}

        if not cuis:
            return {"error": True, "mensajes": "CUIS is required for sync request", "raw": ""}

        url = (config.wsdl_sync_url or '').strip()
        if url.endswith('?wsdl') or '?wsdl' in url:
            url = url.split('?wsdl')[0]

        token = config.token or ''

        body = f"""<soapenv:Envelope xmlns:soapenv="http://schemas.xmlsoap.org/soap/envelope/" xmlns:siat="https://siat.impuestos.gob.bo/">
  <soapenv:Header/>
  <soapenv:Body>
    <siat:sincronizarParametricaTipoPuntoVenta>
      <SolicitudSincronizacion>
        <codigoAmbiente>{config.codigo_ambiente}</codigoAmbiente>
        <codigoPuntoVenta>{company.siat_codigo_punto_venta}</codigoPuntoVenta>
        <codigoSistema>{config.codigo_sistema or ''}</codigoSistema>
        <codigoSucursal>{company.siat_codigo_sucursal}</codigoSucursal>
        <cuis>{cuis}</cuis>
        <nit>{(company.vat or '').strip()}</nit>
      </SolicitudSincronizacion>
    </siat:sincronizarParametricaTipoPuntoVenta>
  </soapenv:Body>
</soapenv:Envelope>"""

        headers = {"Content-Type": "text/xml;charset=UTF-8", "apikey": f"TokenApi {token}"}

        try:
            r = requests.post(url, data=body.encode('utf-8'), headers=headers, timeout=timeout)
        except Exception as e:
            _logger.exception("SIAT HTTP request exception for sincronizarParametricaTipoPuntoVenta")
            return {"error": True, "mensajes": f"HTTP request exception: {e}", "raw": str(e), "http_status": None}

        if r.status_code >= 400:
            _logger.warning("SIAT returned HTTP %s for sync URL %s", r.status_code, url)
            fault_msg = self._extract_soap_fault(r.text)
            if fault_msg:
                return {"error": True, "http_status": r.status_code, "mensajes": f"SIAT error: {fault_msg}", "raw": r.text}
            return {"error": True, "http_status": r.status_code, "mensajes": f"SIAT returned HTTP {r.status_code}", "raw": r.text}

        try:
            root = ET.fromstring(r.content)
        except Exception as e:
            _logger.exception("Failed parsing SIAT sincronizarParametricaTipoPuntoVenta XML")
            return {"error": True, "http_status": r.status_code if 'r' in locals() else None, "mensajes": f"Invalid XML response: {e}", "raw": getattr(r, 'text', '')}

        ns = {'ns': 'https://siat.impuestos.gob.bo/'}
        res_node = root.find('.//ns:RespuestaListaParametricas', ns) or root.find('.//RespuestaListaParametricas')
        if res_node is None:
            fault_msg = self._extract_soap_fault(getattr(r, 'text', ''))
            if fault_msg:
                return {"error": True, "http_status": getattr(r, 'status_code', None), "mensajes": f"SIAT response parsing issue: {fault_msg}", "raw": getattr(r, 'text', '')}
            return {"error": True, "http_status": getattr(r, 'status_code', None), "mensajes": "RespuestaListaParametricas not found", "raw": getattr(r, 'text', '')}

        transaccion = res_node.findtext('ns:transaccion', None, ns) or res_node.findtext('transaccion')
        if transaccion != 'true':
            msgs = []
            for m in res_node.findall('.//{https://siat.impuestos.gob.bo/}mensajesList') + res_node.findall('.//mensajesList'):
                desc = m.findtext('{https://siat.impuestos.gob.bo/}descripcion') or m.findtext('descripcion')
                if desc:
                    msgs.append(desc.strip())
            mensajes_text = " | ".join(msgs) if msgs else 'Transaction failed'
            return {"error": True, "http_status": getattr(r, 'status_code', None), "mensajes": f"SIAT transaction failed: {mensajes_text}", "raw": getattr(r, 'text', '')}

        tipos = []
        for tipo_node in res_node.findall('.//ns:listaCodigos', ns) + res_node.findall('.//listaCodigos'):
            codigo = tipo_node.findtext('ns:codigoClasificador', None, ns) or tipo_node.findtext('codigoClasificador')
            desc = tipo_node.findtext('ns:descripcion', None, ns) or tipo_node.findtext('descripcion')
            if codigo:
                tipos.append({'codigoClasificador': codigo.strip(), 'descripcion': (desc or '').strip()})

        return {"error": False, "transaccion": True, "tipos": tipos, "mensajes": '', "raw": getattr(r, 'text', '')}

    def call_sincronizar_tipos_factura(self, company, config, cuis, timeout=30):
        """
        Call SIAT sincronizarParametricaTiposFactura web service.
        Returns { error, transaccion, tipos, mensajes, raw } (tipos is list of dicts)
        """
        if not config:
            return {"error": True, "mensajes": "No SIAT configuration provided", "raw": ""}

        if not cuis:
            return {"error": True, "mensajes": "CUIS is required for sync request", "raw": ""}

        url = (config.wsdl_sync_url or '').strip()
        if url.endswith('?wsdl') or '?wsdl' in url:
            url = url.split('?wsdl')[0]

        token = config.token or ''

        body = f"""<soapenv:Envelope xmlns:soapenv="http://schemas.xmlsoap.org/soap/envelope/" xmlns:siat="https://siat.impuestos.gob.bo/">
  <soapenv:Header/>
  <soapenv:Body>
    <siat:sincronizarParametricaTiposFactura>
      <SolicitudSincronizacion>
        <codigoAmbiente>{config.codigo_ambiente}</codigoAmbiente>
        <codigoPuntoVenta>{company.siat_codigo_punto_venta}</codigoPuntoVenta>
        <codigoSistema>{config.codigo_sistema or ''}</codigoSistema>
        <codigoSucursal>{company.siat_codigo_sucursal}</codigoSucursal>
        <cuis>{cuis}</cuis>
        <nit>{(company.vat or '').strip()}</nit>
      </SolicitudSincronizacion>
    </siat:sincronizarParametricaTiposFactura>
  </soapenv:Body>
</soapenv:Envelope>"""

        headers = {"Content-Type": "text/xml;charset=UTF-8", "apikey": f"TokenApi {token}"}

        try:
            r = requests.post(url, data=body.encode('utf-8'), headers=headers, timeout=timeout)
        except Exception as e:
            _logger.exception("SIAT HTTP request exception for sincronizarParametricaTiposFactura")
            return {"error": True, "mensajes": f"HTTP request exception: {e}", "raw": str(e), "http_status": None}

        if r.status_code >= 400:
            _logger.warning("SIAT returned HTTP %s for sync URL %s", r.status_code, url)
            fault_msg = self._extract_soap_fault(r.text)
            if fault_msg:
                return {"error": True, "http_status": r.status_code, "mensajes": f"SIAT error: {fault_msg}", "raw": r.text}
            return {"error": True, "http_status": r.status_code, "mensajes": f"SIAT returned HTTP {r.status_code}", "raw": r.text}

        try:
            root = ET.fromstring(r.content)
        except Exception as e:
            _logger.exception("Failed parsing SIAT sincronizarParametricaTiposFactura XML")
            return {"error": True, "http_status": r.status_code if 'r' in locals() else None, "mensajes": f"Invalid XML response: {e}", "raw": getattr(r, 'text', '')}

        ns = {'ns': 'https://siat.impuestos.gob.bo/'}
        res_node = root.find('.//ns:RespuestaListaParametricas', ns) or root.find('.//RespuestaListaParametricas')
        if res_node is None:
            fault_msg = self._extract_soap_fault(getattr(r, 'text', ''))
            if fault_msg:
                return {"error": True, "http_status": getattr(r, 'status_code', None), "mensajes": f"SIAT response parsing issue: {fault_msg}", "raw": getattr(r, 'text', '')}
            return {"error": True, "http_status": getattr(r, 'status_code', None), "mensajes": "RespuestaListaParametricas not found", "raw": getattr(r, 'text', '')}

        transaccion = res_node.findtext('ns:transaccion', None, ns) or res_node.findtext('transaccion')
        if transaccion != 'true':
            msgs = []
            for m in res_node.findall('.//{https://siat.impuestos.gob.bo/}mensajesList') + res_node.findall('.//mensajesList'):
                desc = m.findtext('{https://siat.impuestos.gob.bo/}descripcion') or m.findtext('descripcion')
                if desc:
                    msgs.append(desc.strip())
            mensajes_text = " | ".join(msgs) if msgs else 'Transaction failed'
            return {"error": True, "http_status": getattr(r, 'status_code', None), "mensajes": f"SIAT transaction failed: {mensajes_text}", "raw": getattr(r, 'text', '')}

        tipos = []
        for tipo_node in res_node.findall('.//ns:listaCodigos', ns) + res_node.findall('.//listaCodigos'):
            codigo = tipo_node.findtext('ns:codigoClasificador', None, ns) or tipo_node.findtext('codigoClasificador')
            desc = tipo_node.findtext('ns:descripcion', None, ns) or tipo_node.findtext('descripcion')
            if codigo:
                tipos.append({'codigoClasificador': codigo.strip(), 'descripcion': (desc or '').strip()})

        return {"error": False, "transaccion": True, "tipos": tipos, "mensajes": '', "raw": getattr(r, 'text', '')}

    def call_sincronizar_unidades_medida(self, company, config, cuis, timeout=30):
        """
        Call SIAT sincronizarParametricaUnidadMedida web service.
        Returns dict: { error, transaccion, tipos, mensajes, raw }
        """
        if not config:
            return {"error": True, "mensajes": "No SIAT configuration provided", "raw": ""}

        if not cuis:
            return {"error": True, "mensajes": "CUIS is required for sync request", "raw": ""}

        url = (config.wsdl_sync_url or '').strip()
        if url.endswith('?wsdl') or '?wsdl' in url:
            url = url.split('?wsdl')[0]

        token = config.token or ''

        body = f"""<soapenv:Envelope xmlns:soapenv="http://schemas.xmlsoap.org/soap/envelope/" xmlns:siat="https://siat.impuestos.gob.bo/">
  <soapenv:Header/>
  <soapenv:Body>
    <siat:sincronizarParametricaUnidadMedida>
      <SolicitudSincronizacion>
        <codigoAmbiente>{config.codigo_ambiente}</codigoAmbiente>
        <codigoPuntoVenta>{company.siat_codigo_punto_venta}</codigoPuntoVenta>
        <codigoSistema>{config.codigo_sistema or ''}</codigoSistema>
        <codigoSucursal>{company.siat_codigo_sucursal}</codigoSucursal>
        <cuis>{cuis}</cuis>
        <nit>{(company.vat or '').strip()}</nit>
      </SolicitudSincronizacion>
    </siat:sincronizarParametricaUnidadMedida>
  </soapenv:Body>
</soapenv:Envelope>"""

        headers = {"Content-Type": "text/xml;charset=UTF-8", "apikey": f"TokenApi {token}"}

        try:
            r = requests.post(url, data=body.encode('utf-8'), headers=headers, timeout=timeout)
        except Exception as e:
            _logger.exception("SIAT HTTP request exception for sincronizarParametricaUnidadMedida")
            return {"error": True, "mensajes": f"HTTP request exception: {e}", "raw": str(e), "http_status": None}

        if r.status_code >= 400:
            _logger.warning("SIAT returned HTTP %s for sync URL %s", r.status_code, url)
            fault_msg = self._extract_soap_fault(r.text)
            if fault_msg:
                return {"error": True, "http_status": r.status_code, "mensajes": f"SIAT error: {fault_msg}", "raw": r.text}
            return {"error": True, "http_status": r.status_code, "mensajes": f"SIAT returned HTTP {r.status_code}", "raw": r.text}

        try:
            root = ET.fromstring(r.content)
        except Exception as e:
            _logger.exception("Failed parsing SIAT sincronizarParametricaUnidadMedida XML")
            return {"error": True, "http_status": r.status_code if 'r' in locals() else None, "mensajes": f"Invalid XML response: {e}", "raw": getattr(r, 'text', '')}

        ns = {'ns': 'https://siat.impuestos.gob.bo/'}
        res_node = root.find('.//ns:RespuestaListaParametricas', ns) or root.find('.//RespuestaListaParametricas')
        if res_node is None:
            fault_msg = self._extract_soap_fault(getattr(r, 'text', ''))
            if fault_msg:
                return {"error": True, "http_status": getattr(r, 'status_code', None), "mensajes": f"SIAT response parsing issue: {fault_msg}", "raw": getattr(r, 'text', '')}
            return {"error": True, "http_status": getattr(r, 'status_code', None), "mensajes": "RespuestaListaParametricas not found", "raw": getattr(r, 'text', '')}

        transaccion = res_node.findtext('ns:transaccion', None, ns) or res_node.findtext('transaccion')
        if transaccion != 'true':
            msgs = []
            for m in res_node.findall('.//{https://siat.impuestos.gob.bo/}mensajesList') + res_node.findall('.//mensajesList'):
                desc = m.findtext('{https://siat.impuestos.gob.bo/}descripcion') or m.findtext('descripcion')
                if desc:
                    msgs.append(desc.strip())
            mensajes_text = " | ".join(msgs) if msgs else 'Transaction failed'
            return {"error": True, "http_status": getattr(r, 'status_code', None), "mensajes": f"SIAT transaction failed: {mensajes_text}", "raw": getattr(r, 'text', '')}

        tipos = []
        for tipo_node in res_node.findall('.//ns:listaCodigos', ns) + res_node.findall('.//listaCodigos'):
            codigo = tipo_node.findtext('ns:codigoClasificador', None, ns) or tipo_node.findtext('codigoClasificador')
            desc = tipo_node.findtext('ns:descripcion', None, ns) or tipo_node.findtext('descripcion')
            if codigo:
                tipos.append({'codigoClasificador': codigo.strip(), 'descripcion': (desc or '').strip()})

        return {"error": False, "transaccion": True, "tipos": tipos, "mensajes": '', "raw": getattr(r, 'text', '')}

    def call_sincronizar_tipos_documento_sector(self, company, config, cuis, timeout=30):
        """
        Call SIAT sincronizarParametricaTipoDocumentoSector web service.
        Returns dict { error, transaccion, tipos, mensajes, raw }.
        """
        if not config:
            return {"error": True, "mensajes": "No SIAT configuration provided", "raw": ""}

        if not cuis:
            return {"error": True, "mensajes": "CUIS is required for sync request", "raw": ""}

        url = (config.wsdl_sync_url or '').strip()
        if url.endswith('?wsdl') or '?wsdl' in url:
            url = url.split('?wsdl')[0]

        token = config.token or ''

        body = f"""<soapenv:Envelope xmlns:soapenv="http://schemas.xmlsoap.org/soap/envelope/" xmlns:siat="https://siat.impuestos.gob.bo/">
  <soapenv:Header/>
  <soapenv:Body>
    <siat:sincronizarParametricaTipoDocumentoSector>
      <SolicitudSincronizacion>
        <codigoAmbiente>{config.codigo_ambiente}</codigoAmbiente>
        <codigoPuntoVenta>{company.siat_codigo_punto_venta}</codigoPuntoVenta>
        <codigoSistema>{config.codigo_sistema or ''}</codigoSistema>
        <codigoSucursal>{company.siat_codigo_sucursal}</codigoSucursal>
        <cuis>{cuis}</cuis>
        <nit>{(company.vat or '').strip()}</nit>
      </SolicitudSincronizacion>
    </siat:sincronizarParametricaTipoDocumentoSector>
  </soapenv:Body>
</soapenv:Envelope>"""

        headers = {"Content-Type": "text/xml;charset=UTF-8", "apikey": f"TokenApi {token}"}

        try:
            r = requests.post(url, data=body.encode('utf-8'), headers=headers, timeout=timeout)
        except Exception as e:
            _logger.exception("SIAT HTTP request exception for sincronizarParametricaTipoDocumentoSector")
            return {"error": True, "mensajes": f"HTTP request exception: {e}", "raw": str(e), "http_status": None}

        if r.status_code >= 400:
            _logger.warning("SIAT returned HTTP %s for sync URL %s", r.status_code, url)
            fault_msg = self._extract_soap_fault(r.text)
            if fault_msg:
                return {"error": True, "http_status": r.status_code, "mensajes": f"SIAT error: {fault_msg}", "raw": r.text}
            return {"error": True, "http_status": r.status_code, "mensajes": f"SIAT returned HTTP {r.status_code}", "raw": r.text}

        try:
            root = ET.fromstring(r.content)
        except Exception as e:
            _logger.exception("Failed parsing SIAT sincronizarParametricaTipoDocumentoSector XML")
            return {"error": True, "http_status": r.status_code if 'r' in locals() else None, "mensajes": f"Invalid XML response: {e}", "raw": getattr(r, 'text', '')}

        ns = {'ns': 'https://siat.impuestos.gob.bo/'}
        res_node = root.find('.//ns:RespuestaListaParametricas', ns) or root.find('.//RespuestaListaParametricas')
        if res_node is None:
            fault_msg = self._extract_soap_fault(getattr(r, 'text', ''))
            if fault_msg:
                return {"error": True, "http_status": getattr(r, 'status_code', None), "mensajes": f"SIAT response parsing issue: {fault_msg}", "raw": getattr(r, 'text', '')}
            return {"error": True, "http_status": getattr(r, 'status_code', None), "mensajes": "RespuestaListaParametricas not found", "raw": getattr(r, 'text', '')}

        transaccion = res_node.findtext('ns:transaccion', None, ns) or res_node.findtext('transaccion')
        if transaccion != 'true':
            msgs = []
            for m in res_node.findall('.//{https://siat.impuestos.gob.bo/}mensajesList') + res_node.findall('.//mensajesList'):
                desc = m.findtext('{https://siat.impuestos.gob.bo/}descripcion') or m.findtext('descripcion')
                if desc:
                    msgs.append(desc.strip())
            mensajes_text = " | ".join(msgs) if msgs else 'Transaction failed'
            return {"error": True, "http_status": getattr(r, 'status_code', None), "mensajes": f"SIAT transaction failed: {mensajes_text}", "raw": getattr(r, 'text', '')}

        tipos = []
        for tipo_node in res_node.findall('.//ns:listaCodigos', ns) + res_node.findall('.//listaCodigos'):
            codigo = tipo_node.findtext('ns:codigoClasificador', None, ns) or tipo_node.findtext('codigoClasificador')
            desc = tipo_node.findtext('ns:descripcion', None, ns) or tipo_node.findtext('descripcion')
            if codigo:
                tipos.append({'codigoClasificador': codigo.strip(), 'descripcion': (desc or '').strip()})

        return {"error": False, "transaccion": True, "tipos": tipos, "mensajes": '', "raw": getattr(r, 'text', '')}

    def call_sincronizar_tipos_emision(self, company, config, cuis, timeout=30):
        """
        Call SIAT sincronizarParametricaTipoEmision web service.
        Returns dict { error, transaccion, tipos, mensajes, raw }.
        """
        if not config:
            return {"error": True, "mensajes": "No SIAT configuration provided", "raw": ""}

        if not cuis:
            return {"error": True, "mensajes": "CUIS is required for sync request", "raw": ""}

        url = (config.wsdl_sync_url or '').strip()
        if url.endswith('?wsdl') or '?wsdl' in url:
            url = url.split('?wsdl')[0]

        token = config.token or ''

        body = f"""<soapenv:Envelope xmlns:soapenv="http://schemas.xmlsoap.org/soap/envelope/" xmlns:siat="https://siat.impuestos.gob.bo/">
  <soapenv:Header/>
  <soapenv:Body>
    <siat:sincronizarParametricaTipoEmision>
      <SolicitudSincronizacion>
        <codigoAmbiente>{config.codigo_ambiente}</codigoAmbiente>
        <codigoPuntoVenta>{company.siat_codigo_punto_venta}</codigoPuntoVenta>
        <codigoSistema>{config.codigo_sistema or ''}</codigoSistema>
        <codigoSucursal>{company.siat_codigo_sucursal}</codigoSucursal>
        <cuis>{cuis}</cuis>
        <nit>{(company.vat or '').strip()}</nit>
      </SolicitudSincronizacion>
    </siat:sincronizarParametricaTipoEmision>
  </soapenv:Body>
</soapenv:Envelope>"""

        headers = {"Content-Type": "text/xml;charset=UTF-8", "apikey": f"TokenApi {token}"}

        try:
            r = requests.post(url, data=body.encode('utf-8'), headers=headers, timeout=timeout)
        except Exception as e:
            _logger.exception("SIAT HTTP request exception for sincronizarParametricaTipoEmision")
            return {"error": True, "mensajes": f"HTTP request exception: {e}", "raw": str(e), "http_status": None}

        if r.status_code >= 400:
            _logger.warning("SIAT returned HTTP %s for sync URL %s", r.status_code, url)
            fault_msg = self._extract_soap_fault(r.text)
            if fault_msg:
                return {"error": True, "http_status": r.status_code, "mensajes": f"SIAT error: {fault_msg}", "raw": r.text}
            return {"error": True, "http_status": r.status_code, "mensajes": f"SIAT returned HTTP {r.status_code}", "raw": r.text}

        try:
            root = ET.fromstring(r.content)
        except Exception as e:
            _logger.exception("Failed parsing SIAT sincronizarParametricaTipoEmision XML")
            return {"error": True, "http_status": r.status_code if 'r' in locals() else None, "mensajes": f"Invalid XML response: {e}", "raw": getattr(r, 'text', '')}

        ns = {'ns': 'https://siat.impuestos.gob.bo/'}
        res_node = root.find('.//ns:RespuestaListaParametricas', ns) or root.find('.//RespuestaListaParametricas')
        if res_node is None:
            fault_msg = self._extract_soap_fault(getattr(r, 'text', ''))
            if fault_msg:
                return {"error": True, "http_status": getattr(r, 'status_code', None), "mensajes": f"SIAT response parsing issue: {fault_msg}", "raw": getattr(r, 'text', '')}
            return {"error": True, "http_status": getattr(r, 'status_code', None), "mensajes": "RespuestaListaParametricas not found", "raw": getattr(r, 'text', '')}

        transaccion = res_node.findtext('ns:transaccion', None, ns) or res_node.findtext('transaccion')
        if transaccion != 'true':
            msgs = []
            for m in res_node.findall('.//{https://siat.impuestos.gob.bo/}mensajesList') + res_node.findall('.//mensajesList'):
                desc = m.findtext('{https://siat.impuestos.gob.bo/}descripcion') or m.findtext('descripcion')
                if desc:
                    msgs.append(desc.strip())
            mensajes_text = " | ".join(msgs) if msgs else 'Transaction failed'
            return {"error": True, "http_status": getattr(r, 'status_code', None), "mensajes": f"SIAT transaction failed: {mensajes_text}", "raw": getattr(r, 'text', '')}

        tipos = []
        for tipo_node in res_node.findall('.//ns:listaCodigos', ns) + res_node.findall('.//listaCodigos'):
            codigo = tipo_node.findtext('ns:codigoClasificador', None, ns) or tipo_node.findtext('codigoClasificador')
            desc = tipo_node.findtext('ns:descripcion', None, ns) or tipo_node.findtext('descripcion')
            if codigo:
                tipos.append({'codigoClasificador': codigo.strip(), 'descripcion': (desc or '').strip()})

        return {"error": False, "transaccion": True, "tipos": tipos, "mensajes": '', "raw": getattr(r, 'text', '')}

#--- funciones para facturacion desde PDV
    def validar_xml_contra_xsd(self, xml_string, xsd_path=None):
        """
        Valida el XML contra el XSD de SIAT

        :param xml_string: String del XML a validar
        :param xsd_path: Ruta al archivo XSD (opcional)
        :return: dict con resultado de validación
        """
        try:
            _logger.info("Validando XML contra XSD de SIAT...")

            # Obtener ruta del XSD
            module_path = get_module_path('alpha_siat')
            if 'facturaElectronicaCompraVenta' in xml_string:
                _logger.info('Factura Electronica: saltando validacion XSD local')
                return {'valido': True, 'errores': []}
            xsd_path = os.path.join(module_path, 'data', 'facturaComputarizadaCompraVenta.xsd')

            if not os.path.exists(xsd_path):
                _logger.warning(f"XSD no encontrado en {xsd_path}, saltando validacion")
                return {'valido': True, 'errores': [], 'warning': 'XSD no disponible'}

            # Parsear el XML
            xml_doc = etree.fromstring(xml_string.encode('utf-8'))

            # Cargar el XSD
            with open(xsd_path, 'rb') as xsd_file:
                xsd_doc = etree.parse(xsd_file)
                xsd_schema = etree.XMLSchema(xsd_doc)

            # Validar
            if xsd_schema.validate(xml_doc):
                _logger.info("XML válido contra XSD")
                return {'valido': True, 'errores': []}
            else:
                errores = []
                for error in xsd_schema.error_log:
                    error_msg = f"Linea {error.line}: {error.message}"
                    errores.append(error_msg)
                    _logger.error(f"  ✗ {error_msg}")

                return {'valido': False, 'errores': errores}

        except Exception as e:
            _logger.error(f"Error validando XML: {str(e)}", exc_info=True)
            return {'valido': False, 'errores': [str(e)]}

    def comprimir_xml_gzip(self, xml_string):
        """
        Comprime el XML en formato GZIP

        :param xml_string: String del XML a comprimir
        :return: bytes del archivo comprimido
        """
        try:
            # Convertir string a bytes si es necesario
            if isinstance(xml_string, str):
                xml_bytes = xml_string.encode('utf-8')
            else:
                xml_bytes = xml_string

            # Comprimir con GZIP
            compressed = gzip.compress(xml_bytes)

            _logger.info(f"XML comprimido: {len(xml_bytes)} bytes -> {len(compressed)} bytes")
            return compressed

        except Exception as e:
            _logger.error(f"Error comprimiendo XML: {str(e)}", exc_info=True)
            raise

    def calcular_hash_sha256(self, data):
        """
        Calcula el hash SHA-256 de los datos

        :param data: bytes a hashear
        :return: string hexadecimal del hash en minúsculas
        """
        try:
            hash_obj = hashlib.sha256()
            hash_obj.update(data)
            hash_hex = hash_obj.hexdigest().lower()

            _logger.info(f"Hash SHA-256 calculado: {hash_hex}")
            return hash_hex

        except Exception as e:
            _logger.error(f"Error calculando hash: {str(e)}", exc_info=True)
            raise

    def enviar_factura_siat(self, company, config, cuis, cufd, xml_string):
        """
        Envía la factura al servicio SIAT de recepción

        :param company: Compañía (res.company)
        :param config: Configuración SIAT
        :param cuis: Código CUIS válido
        :param cufd: Código CUFD válido
        :param xml_string: XML de la factura
        :return: dict con resultado del envío
        """
        _logger.info("=" * 100)
        _logger.info("INICIANDO ENVIO DE FACTURA A SIAT")
        _logger.info("=" * 100)

        try:
            # Validar parámetros
            if not company:
                return {'error': True, 'mensajes': 'Compania no proporcionada'}
            if not config:
                return {'error': True, 'mensajes': 'Configuracion SIAT no proporcionada'}
            if not cuis:
                return {'error': True, 'mensajes': 'CUIS no proporcionado'}
            if not cufd:
                return {'error': True, 'mensajes': 'CUFD no proporcionado'}
            if not xml_string:
                return {'error': True, 'mensajes': 'XML de factura no proporcionado'}

            _logger.info(f"Parametros recibidos:")
            _logger.info(f"  Compania: {company.name}")
            _logger.info(f"  NIT: {company.vat}")
            _logger.info(f"  CUIS: {cuis[:20]}...")
            _logger.info(f"  CUFD: {cufd[:20]}...")
            _logger.info(f"  Tamano XML: {len(xml_string)} bytes")

            # PASO 1: VALIDAR XML CONTRA XSD
            _logger.info("Paso 1: Validando XML contra XSD...")
            validacion = self.validar_xml_contra_xsd(xml_string)

            if not validacion['valido']:
                errores_str = '\n'.join(validacion['errores'])
                error_msg = (
                    f"XML INVALIDO - No cumple con el XSD de SIAT\n\n"
                    f"Errores encontrados:\n{errores_str}\n\n"
                    f"El XML debe corregirse antes de enviarlo a SIAT."
                )
                _logger.error(error_msg)
                return {
                    'error': True,
                    'mensajes': error_msg,
                    'errores_validacion': validacion['errores']
                }

            _logger.info("XML validado correctamente contra XSD")

            # Paso 2: Comprimir XML
            _logger.info("Paso 2: Comprimiendo XML en GZIP...")
            xml_comprimido = self.comprimir_xml_gzip(xml_string)

            # Paso 3: Calcular hash del archivo comprimido
            _logger.info("Paso 3: Calculando hash SHA-256...")
            hash_archivo = self.calcular_hash_sha256(xml_comprimido)

            # Paso 4: Codificar en base64 para envío
            _logger.info("Paso 4: Codificando archivo en base64...")
            archivo_base64 = base64.b64encode(xml_comprimido).decode('utf-8')

            # Paso 5: Preparar URL del servicio
            _logger.info("Paso 5: Preparando URL del servicio...")

            # USAR EL NUEVO CAMPO wsdl_compra_venta
            url = (config.wsdl_compra_venta or '').strip()

            if not url:
                return {
                    'error': True,
                    'mensajes': 'URL de facturacion no configurada (wsdl_compra_venta). Configure la URL en SIAT Config.'
                }

            # Limpiar ?wsdl si existe
            if url.endswith('?wsdl') or '?wsdl' in url:
                url = url.split('?wsdl')[0]

            _logger.info(f"URL servicio: {url}")

            # Paso 6: Preparar solicitud SOAP
            _logger.info("Paso 6: Preparando solicitud SOAP...")

            ahora_utc = datetime.now(timezone.utc)

            # Convertir a hora de Bolivia (UTC-4)
            bolivia_tz = timezone(timedelta(hours=-4))
            ahora_bolivia = ahora_utc.astimezone(bolivia_tz)

            # Formatear fecha para SIAT (sin zona horaria en el string)
            fecha_envio = ahora_bolivia.strftime('%Y-%m-%dT%H:%M:%S.%f')[:-3]

            _logger.info(f"Hora UTC: {ahora_utc.strftime('%Y-%m-%d %H:%M:%S')}")
            _logger.info(f"Hora Bolivia (UTC-4): {ahora_bolivia.strftime('%Y-%m-%d %H:%M:%S')}")
            _logger.info(f"Fecha envio formateada: {fecha_envio}")

            nit = (company.vat or '').strip()

            body = f"""<soapenv:Envelope xmlns:soapenv="http://schemas.xmlsoap.org/soap/envelope/" xmlns:siat="https://siat.impuestos.gob.bo/">
    <soapenv:Header/>
    <soapenv:Body>
      <siat:recepcionFactura>
         <SolicitudServicioRecepcionFactura>
            <codigoAmbiente>{config.codigo_ambiente}</codigoAmbiente>
            <codigoDocumentoSector>1</codigoDocumentoSector>
            <codigoEmision>1</codigoEmision>
            <codigoModalidad>{config.modalidad}</codigoModalidad>
            <codigoPuntoVenta>{company.siat_codigo_punto_venta or 0}</codigoPuntoVenta>
            <codigoSistema>{config.codigo_sistema or ''}</codigoSistema>
            <codigoSucursal>{company.siat_codigo_sucursal or 0}</codigoSucursal>
            <cufd>{cufd}</cufd>
            <cuis>{cuis}</cuis>
            <nit>{nit}</nit>
            <tipoFacturaDocumento>1</tipoFacturaDocumento>
            <archivo>{archivo_base64}</archivo>
            <fechaEnvio>{fecha_envio}</fechaEnvio>
            <hashArchivo>{hash_archivo}</hashArchivo>
         </SolicitudServicioRecepcionFactura>
      </siat:recepcionFactura>
    </soapenv:Body>
    </soapenv:Envelope>"""

            headers = {
                "Content-Type": "text/xml;charset=UTF-8",
                "apikey": f"TokenApi {config.token or ''}"
            }

            _logger.info("\n" + "=" * 100)
            _logger.info("PARAMETROS DECODIFICADOS:")
            _logger.info("=" * 100)
            _logger.info(f"  NIT: {nit}")
            _logger.info(f"  CUIS: {cuis}")
            _logger.info(f"  CUFD: {cufd}")
            _logger.info(f"  Codigo Ambiente: {config.codigo_ambiente}")
            _logger.info(f"  Codigo Modalidad: {config.modalidad}")
            _logger.info(f"  Codigo Sistema: {config.codigo_sistema or 'N/A'}")
            _logger.info(f"  Codigo Sucursal: {company.siat_codigo_sucursal or 0}")
            _logger.info(f"  Codigo Punto Venta: {company.siat_codigo_punto_venta or 0}")
            _logger.info(f"  Hash Archivo: {hash_archivo}")
            _logger.info(f"  Fecha Envio: {fecha_envio}")
            _logger.info(f"  Tamaño Archivo Base64: {len(archivo_base64)} caracteres")
            _logger.info("=" * 100)

            try:
                xml_decodificado = gzip.decompress(base64.b64decode(archivo_base64)).decode('utf-8')
                _logger.info("\n" + "=" * 100)
                _logger.info("XML FACTURA DECODIFICADO (contenido del archivo):")
                _logger.info("=" * 100)
                _logger.info(xml_decodificado)
                _logger.info("=" * 100)
            except Exception as e:
                _logger.warning(f"No se pudo decodificar el XML del archivo: {str(e)}")

            # Paso 7: Enviar solicitud
            _logger.info("Paso 7: Enviando solicitud a SIAT...")

            try:
                response = requests.post(
                    url,
                    data=body.encode('utf-8'),
                    headers=headers,
                    timeout=60
                )
            except requests.exceptions.Timeout:
                return {
                    'error': True,
                    'mensajes': 'Timeout: El servicio de SIAT no respondio en 60 segundos'
                }
            except requests.exceptions.ConnectionError as e:
                return {
                    'error': True,
                    'mensajes': f'Error de conexion: No se pudo conectar con SIAT. Verifique su conexion a internet. Detalle: {str(e)}'
                }
            except Exception as e:
                return {
                    'error': True,
                    'mensajes': f'Error en peticion HTTP: {str(e)}'
                }

            _logger.info(f"Respuesta HTTP: {response.status_code}")

            if response.status_code >= 400:
                _logger.error(f"Error HTTP {response.status_code}")
                _logger.error(f"Respuesta: {response.text[:500]}...")
                return {
                    'error': True,
                    'http_status': response.status_code,
                    'mensajes': f"Error HTTP {response.status_code}: Servicio de SIAT no disponible",
                    'raw': response.text
                }

            # Parsear respuesta
            resultado = self._parsear_respuesta_recepcion_factura(response.text)

            _logger.info("=" * 100)
            _logger.info("RESULTADO ENVIO FACTURA:")
            _logger.info(f"  Error: {resultado.get('error', False)}")
            _logger.info(f"  Estado: {resultado.get('estado', 'N/A')}")
            _logger.info(f"  Descripcion: {resultado.get('descripcion_estado', 'N/A')}")
            _logger.info(f"  Codigo Recepcion: {resultado.get('codigoRecepcion', 'N/A')}")
            _logger.info(f"  Transaccion: {resultado.get('transaccion', 'N/A')}")
            _logger.info(f"  Mensajes: {resultado.get('mensajes', 'N/A')}")
            _logger.info("=" * 100)

            return resultado

        except Exception as e:
            _logger.error(f"Error critico enviando factura: {str(e)}", exc_info=True)
            return {
                'error': True,
                'mensajes': f"Error critico: {str(e)}"
            }

    def _parsear_respuesta_recepcion_factura(self, xml_text):
        """
        Parsea la respuesta del servicio de recepción de facturas

        :param xml_text: XML de respuesta de SIAT
        :return: dict con datos parseados
        """
        try:
            root = etree.fromstring(xml_text.encode('utf-8'))

            ns = {'ns': 'https://siat.impuestos.gob.bo/'}

            # Buscar RespuestaServicioFacturacion
            resp_node = root.find('.//ns:RespuestaServicioFacturacion', ns) or \
                        root.find('.//RespuestaServicioFacturacion')

            if resp_node is None:
                # Buscar SOAP Fault
                fault = root.find('.//{http://schemas.xmlsoap.org/soap/envelope/}Fault')
                if fault is not None:
                    faultstring = fault.findtext('faultstring', '')
                    return {
                        'error': True,
                        'mensajes': f"SOAP Fault: {faultstring}",
                        'raw': xml_text
                    }

                return {
                    'error': True,
                    'mensajes': 'No se encontró RespuestaServicioFacturacion en la respuesta',
                    'raw': xml_text
                }

            # Extraer campos
            codigo_descripcion = resp_node.findtext('ns:codigoDescripcion', None, ns) or \
                                 resp_node.findtext('codigoDescripcion', '')

            codigo_estado = resp_node.findtext('ns:codigoEstado', None, ns) or \
                            resp_node.findtext('codigoEstado', '')

            codigo_recepcion = resp_node.findtext('ns:codigoRecepcion', None, ns) or \
                               resp_node.findtext('codigoRecepcion', '')

            transaccion = resp_node.findtext('ns:transaccion', None, ns) or \
                          resp_node.findtext('transaccion', '')

            # Extraer mensajes
            mensajes = []
            for msg in resp_node.findall('.//ns:mensajesList', ns) + resp_node.findall('.//mensajesList'):
                codigo = msg.findtext('ns:codigo', None, ns) or msg.findtext('codigo', '')
                descripcion = msg.findtext('ns:descripcion', None, ns) or msg.findtext('descripcion', '')
                if descripcion:
                    mensajes.append(f"[{codigo}] {descripcion}")

            mensajes_text = " | ".join(mensajes) if mensajes else codigo_descripcion

            # Determinar si hubo error
            # 908 = Validado, 904 = Observado
            estado_exitoso = codigo_estado in ['908', '907']

            return {
                'error': not estado_exitoso,
                'estado': codigo_estado,
                'descripcion_estado': codigo_descripcion,
                'codigoRecepcion': codigo_recepcion,
                'transaccion': transaccion == 'true',
                'mensajes': mensajes_text,
                'raw': xml_text
            }

        except Exception as e:
            _logger.error(f"Error parseando respuesta: {str(e)}", exc_info=True)
            return {
                'error': True,
                'mensajes': f"Error parseando respuesta: {str(e)}",
                'raw': xml_text
            }

    def anular_factura_siat(self, company, config, datos_anulacion):
        """Envía solicitud de anulación a SIAT"""

        _logger.info("Enviando solicitud de anulación a SIAT...")

        try:
            # URL del servicio
            url = (config.wsdl_compra_venta or '').strip()
            if not url:
                return {'error': True, 'mensajes': 'URL de anulación no configurada'}

            if url.endswith('?wsdl'):
                url = url.split('?wsdl')[0]

            # Preparar solicitud SOAP
            body = f"""<soapenv:Envelope xmlns:soapenv="http://schemas.xmlsoap.org/soap/envelope/" xmlns:siat="https://siat.impuestos.gob.bo/">
    <soapenv:Header/>
    <soapenv:Body>
        <siat:anulacionFactura>
            <SolicitudServicioAnulacionFactura>
                <codigoAmbiente>{datos_anulacion['codigoAmbiente']}</codigoAmbiente>
                <codigoPuntoVenta>{datos_anulacion.get('codigoPuntoVenta', 0)}</codigoPuntoVenta>
                <codigoSistema>{datos_anulacion['codigoSistema']}</codigoSistema>
                <codigoSucursal>{datos_anulacion['codigoSucursal']}</codigoSucursal>
                <nit>{datos_anulacion['nit']}</nit>
                <codigoDocumentoSector>{datos_anulacion['codigoDocumentoSector']}</codigoDocumentoSector>
                <codigoEmision>{datos_anulacion['codigoEmision']}</codigoEmision>
                <codigoModalidad>{datos_anulacion['codigoModalidad']}</codigoModalidad>
                <cufd>{datos_anulacion['cufd']}</cufd>
                <cuis>{datos_anulacion['cuis']}</cuis>
                <tipoFacturaDocumento>{datos_anulacion['tipoFacturaDocumento']}</tipoFacturaDocumento>
                <codigoMotivo>{datos_anulacion['codigoMotivo']}</codigoMotivo>
                <cuf>{datos_anulacion['cuf']}</cuf>
            </SolicitudServicioAnulacionFactura>
        </siat:anulacionFactura>
    </soapenv:Body>
</soapenv:Envelope>"""

            headers = {
                "Content-Type": "text/xml;charset=UTF-8",
                "apikey": f"TokenApi {config.token or ''}"
            }

            # Enviar solicitud
            response = requests.post(url, data=body.encode('utf-8'), headers=headers, timeout=60)

            if response.status_code >= 400:
                return {
                    'error': True,
                    'mensajes': f"Error HTTP {response.status_code}"
                }

            # Parsear respuesta
            root = etree.fromstring(response.text.encode('utf-8'))
            ns = {'ns': 'https://siat.impuestos.gob.bo/'}

            resp_node = root.find('.//ns:RespuestaServicioFacturacion', ns) or \
                        root.find('.//RespuestaServicioFacturacion')

            if resp_node is None:
                return {'error': True, 'mensajes': 'Respuesta inválida de SIAT'}

            codigo_estado = resp_node.findtext('ns:codigoEstado', None, ns) or \
                            resp_node.findtext('codigoEstado', '')

            codigo_descripcion = resp_node.findtext('ns:codigoDescripcion', None, ns) or \
                                 resp_node.findtext('codigoDescripcion', '')

            # Estados exitosos: 905=Anulado, 908=Validado
            estado_exitoso = codigo_estado in ['905', '908']

            _logger.info(f"Respuesta SIAT - Estado: {codigo_estado} - {codigo_descripcion}")

            return {
                'error': not estado_exitoso,
                'estado': codigo_estado,
                'mensajes': codigo_descripcion
            }

        except Exception as e:
            _logger.error(f"Error en anulación: {str(e)}", exc_info=True)
            return {'error': True, 'mensajes': str(e)}
