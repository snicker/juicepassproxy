#
# Original source  : https://github.com/philipkocanda/juicebox-protocol
#
class JuiceboxCRC:
    ALPHABET = "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ"

    def __init__(self, payload: str) -> None:
        self.payload = payload
        pass

    def integer(self) -> int:
        return self.crc(self.payload)


    def base35(self) -> str:
        return self.base35encode(self.integer())


    def inspect(self) -> dict:
        return {
            "payload": self.payload,
            "base35": self.base35(),
            "integer": self.integer(),
        }

    def base35encode(self, number: int) -> str:
        base35 = ""

        while number > 1:
            number, i = divmod(number, 35)
            if i == 24:
                i = 35
            base35 = base35 + self.ALPHABET[i]

        return base35


    def base35decode(self, number: str) -> int:
        decimal = 0
        for i, s in enumerate(reversed(number)):
            decimal += self.ALPHABET.index(s) * (35**i)
        return decimal


    def crc(self, data: str) -> int:
        h = 0
        for s in data:
            h ^= (h << 5) + (h >> 2) + ord(s)
            h &= 0xFFFF
        return h

