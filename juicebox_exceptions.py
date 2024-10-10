#
# Original source  : https://github.com/philipkocanda/juicebox-protocol
#
class JuiceboxException(Exception):
    "Generic exception class for this library"
    pass

class JuiceboxInvalidMessageFormat(JuiceboxException):
    pass


class JuiceboxCRCError(JuiceboxException):
    pass
