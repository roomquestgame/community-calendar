"""One Vercel Python entrypoint for the restricted collector routes."""
from api.geocode import handler as GeocoderHandler
from api.preview import handler as PreviewHandler
from api.chambermaster import handler as ChamberMasterHandler
from api.provider_pilot import handler as PilotHandler


class handler(PreviewHandler, GeocoderHandler, ChamberMasterHandler, PilotHandler):
    """Reuse both handlers' authentication without introducing public inputs."""

    def do_GET(self):
        if self.path in ("/api/provider-pilot", "/api/provider-pilot/orangeburg"):
            return PilotHandler.do_GET(self)
        if self.path == "/api/chambermaster":
            return ChamberMasterHandler.do_GET(self)
        if self.path == "/api/geocode":
            return GeocoderHandler.do_GET(self)
        return PreviewHandler.do_GET(self)

    def do_POST(self):
        if self.path in ("/api/provider-pilot", "/api/provider-pilot/orangeburg"):
            return PilotHandler.do_POST(self)
        if self.path == "/api/chambermaster":
            return ChamberMasterHandler.do_POST(self)
        if self.path == "/api/geocode":
            return GeocoderHandler.do_POST(self)
        return PreviewHandler.do_POST(self)

    def log_message(self, *args):
        if self.path == "/api/geocode":
            return
        return PreviewHandler.log_message(self, *args)
