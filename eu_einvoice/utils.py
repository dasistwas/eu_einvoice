def identity(value):
	"""Used for dummy translation"""
	return value


def format_heading(heading: str) -> str:
	return "-" * (len(heading) + 4) + "\n" + f"{heading}\n" + "-" * (len(heading) + 4) + "\n"
