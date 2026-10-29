import asyncio
from types import SimpleNamespace
from unittest.mock import patch

from oneshelf.net.governor import Priority, TrafficGovernor
from oneshelf.net.policy import EgressPolicy
from oneshelf.sources.service import SourceService
from tests.unit.plugins.native.test_noorbook_package import package


def test_concurrent_first_use_owns_and_closes_exactly_one_transport(db,tmp_path):
    pkg=package(tmp_path)
    created=[]
    class Client:
        def __init__(self,*a,**kw): self.closed=False; created.append(self)
        async def __aenter__(self): await asyncio.sleep(0.01); return self
        async def __aexit__(self,*exc): self.closed=True
    async def scenario():
        async with SourceService(db,None,TrafficGovernor(),None) as service:
            with patch('oneshelf.net.ech.EchClient',Client):
                first,second=await asyncio.gather(service._native_provider(pkg,Priority.READER),
                                                  service._native_provider(pkg,Priority.READER))
                assert first.client is second.client
        assert len(created)==1 and created[0].closed
    asyncio.run(scenario())
