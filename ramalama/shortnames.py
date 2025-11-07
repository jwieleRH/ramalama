import configparser
import os
import sysconfig


class Shortnames:
    """Shortnames utility class"""

    shortnames: dict[str, str] = {}

    def __init__(self):
        data_path = sysconfig.get_path("data")
        file_paths = [
            "./shortnames/shortnames.conf",  # for development
            "./shortnames.conf",  # for development
            os.path.expanduser("~/.config/ramalama/shortnames.conf"),
            f"{data_path}/share/ramalama/shortnames.conf",
            os.path.expanduser("~/.local/share/ramalama/shortnames.conf"),
            os.path.expanduser("~/.local/pipx/venvs/ramalama/share/ramalama/shortnames.conf"),
            "/etc/ramalama/shortnames.conf",
            "/usr/share/ramalama/shortnames.conf",
            "/usr/local/share/ramalama/shortnames.conf",
        ]

        self.paths = []
        for file_path in file_paths:
            config = configparser.ConfigParser(delimiters="=")
            config.read(file_path)
            if "shortnames" in config:
                self.paths.append(os.path.realpath(file_path))
                self.shortnames.update(config["shortnames"])

        # Remove leading and trailing quotes from keys and values
        self.shortnames = {self._strip_quotes(key): self._strip_quotes(value) for key, value in self.shortnames.items()}

    def _strip_quotes(self, s) -> str:
        return s.strip("'\"")

    def resolve(self, model) -> str | None:
        return self.shortnames.get(model, model)
