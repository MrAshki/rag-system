from typing import Dict, Iterable, List, Optional, Protocol


Message = Dict[str, str]


class ChatProvider(Protocol):
    name: str
    model: str

    def chat(
        self,
        messages: List[Message],
        options: Optional[Dict] = None,
        response_format: Optional[str] = None,
    ) -> str:
        ...

    def stream_chat(
        self,
        messages: List[Message],
        options: Optional[Dict] = None,
    ) -> Iterable[str]:
        ...

    def health(self) -> Dict:
        ...
