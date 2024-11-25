from pathlib import Path

from lxml import objectify
from saxonche import PySaxonProcessor

STYLESHEET = "EN16931-CII-validation-preprocessed.xsl"


def get_validation_errors(xml_string: str) -> list[str]:
	stylesheet_path = Path(__file__).parent / STYLESHEET
	report = get_validation_report(xml_string, str(stylesheet_path))
	return extract_failed_asserts(report)


def extract_failed_asserts(xml: bytes) -> list[str]:
	root = objectify.fromstring(xml)
	failed_asserts = root.xpath(
		"//svrl:failed-assert/svrl:text",
		namespaces={"svrl": "http://purl.oclc.org/dsdl/svrl"},
	)
	return [failed_assert.text for failed_assert in failed_asserts]


def get_validation_report(xml_string: str, stylesheet_file: str) -> bytes:
	with PySaxonProcessor(license=False) as proc:
		xslt30_processor = proc.new_xslt30_processor()
		input_node = proc.parse_xml(xml_text=xml_string)
		executable = xslt30_processor.compile_stylesheet(stylesheet_file=stylesheet_file)
		report = executable.transform_to_string(xdm_node=input_node)

	return report.encode("utf-8")
