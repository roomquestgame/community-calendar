"""One Vercel Python entrypoint for the restricted collector routes."""
from api.geocode import handler as GeocoderHandler
from api.preview import handler as PreviewHandler


class handler(PreviewHandler, GeocoderHandler):
    """Reuse both handlers' authentication without introducing public inputs."""

    def do_GET(self):
        if self.path == "/api/geocode":
            return GeocoderHandler.do_GET(self)
        return PreviewHandler.do_GET(self)

    def do_POST(self):
        if self.path == "/api/geocode":
            return GeocoderHandler.do_POST(self)
        return PreviewHandler.do_POST(self)

    def log_message(self, *args):
        if self.path == "/api/geocode":
            return
        return PreviewHandler.log_message(self, *args)
