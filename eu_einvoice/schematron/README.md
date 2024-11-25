How to generate `EN16931-CII-validation-preprocessed.xsl`:

- Download `EN16931-CII-validation-preprocessed.sch` from https://github.com/ConnectingEurope/eInvoicing-EN16931/blob/7ce3772aff315588f37e38b509173f253d340e45/cii/schematron/preprocessed/EN16931-CII-validation-preprocessed.sch and copy into a folder.
- Download `schxslt-1.10.1-xslt-only.zip` from https://github.com/schxslt/schxslt/releases/tag/v1.10.1, unzip and copy into the same folder.
- Run the following Python code in the same folder.

```python
from saxonche import PySaxonProcessor

SCHEMATRON = "EN16931-CII-validation-preprocessed.sch"
SCHEMATRON_PIPELINE = "schxslt-1.10.1/2.0/pipeline-for-svrl.xsl"


with PySaxonProcessor(license=False) as proc:
	xslt30_processor = proc.new_xslt30_processor()
	xslt30_processor.set_cwd(".")

	# Save the compiled schematron to a file
	xslt30_processor.transform_to_file(
		source_file=SCHEMATRON, stylesheet_file=SCHEMATRON_PIPELINE, output_file=SCHEMATRON[:-4] + ".xsl"
	)
```
