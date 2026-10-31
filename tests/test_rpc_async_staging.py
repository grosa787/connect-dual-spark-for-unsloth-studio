from pathlib import Path
import subprocess
import tempfile
import unittest
import re
import shutil

from dual_spark.fastload import patch_rpc_source


SOURCE = '''static bool rpc_use_hash_cache(const ggml_tensor * tensor, size_t size) {
    return size > HASH_THRESHOLD && tensor->buffer->usage == GGML_BACKEND_BUFFER_USAGE_WEIGHTS;
}

static void ggml_backend_rpc_device_get_props(ggml_backend_dev_t dev, struct ggml_backend_dev_props * props) {
    props->caps = {
        /* .async                 = */ true,
        /* .host_buffer           = */ false,
        /* .buffer_from_host_ptr  = */ false,
        /* .events                = */ true,
        /* .mmap_support          = */ true,
    };
}

static const struct ggml_backend_device_i ggml_backend_rpc_device_i = {
    /* .get_buffer_type      = */ ggml_backend_rpc_device_get_buffer_type,
    /* .get_host_buffer_type = */ NULL,
    /* .buffer_from_host_ptr = */ NULL,
};

void rpc_dispatcher::graph_compute(uint32_t device, const ggml_cgraph * cgraph) {
    std::lock_guard<std::mutex> lock(graph_mutex);
    auto & device_graph_uids = graph_uids[device];
    this->last_uid = cgraph->uid;
}
'''


class RpcAsyncStagingTests(unittest.TestCase):
    def test_rpc_exposes_cpu_staging_and_keeps_device_capabilities(self):
        result=patch_rpc_source(SOURCE)
        self.assertIn('/* .host_buffer           = */ true,',result)
        self.assertIn('ggml_backend_cpu_buffer_type()',result)
        self.assertIn('/* .get_host_buffer_type = */ ggml_backend_rpc_device_get_host_buffer_type,',result)
        for field in ('/* .async                 = */ true,','/* .buffer_from_host_ptr  = */ false,','/* .events                = */ true,'):
            self.assertIn(field,result)
        self.assertEqual(result.count('GGML_RPC_NO_HASH_CACHE'),2)

    def test_unknown_host_buffer_contract_refuses_before_build(self):
        for source in (SOURCE.replace('/* .host_buffer           = */ false,','/* .host_buffer           = */ true,'),SOURCE.replace('/* .get_host_buffer_type = */ NULL,','/* .get_host_buffer_type = */ another_callback,')):
            with self.subTest(source=source):
                with self.assertRaisesRegex(ValueError,'async staging source drift'):
                    patch_rpc_source(source)

    def test_does_not_rewrite_protocol_or_tensor_payload_functions(self):
        untouched='\nstatic void serialize_weights(const void * data, size_t n) { memcpy(dst, data, n); }\n'
        result=patch_rpc_source(SOURCE+untouched)
        self.assertTrue(result.endswith(untouched))

    def test_distributed_patch_assets_match_the_runtime_transformation(self):
        patches=Path(__file__).parents[1]/'dual_spark/patches'
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory); source=root/'ggml/src/ggml-rpc/ggml-rpc.cpp'
            source.parent.mkdir(parents=True); source.write_text(SOURCE)
            for name in ('rpc-no-hash-cache.patch','rpc-async-staging.patch','rpc-graph-cache-profile.patch'):
                result=subprocess.run(['patch','-p1','--batch','--forward','--fuzz=0','-i',str(patches/name)],cwd=root,text=True,capture_output=True)
                self.assertEqual(result.returncode,0,result.stdout+result.stderr)
            self.assertEqual(source.read_text(),patch_rpc_source(SOURCE))

    @unittest.skipUnless(shutil.which('c++'),'A C++ compiler is needed for the graph UID behavior check')
    def test_low_memory_mode_changes_only_wire_uid_and_preserves_default(self):
        patched=patch_rpc_source(SOURCE)
        body=re.search(r'void rpc_dispatcher::graph_compute\([^\n]+\) \{.*?^}',patched,re.S|re.M).group(0)
        code='''#include <cstdint>
#include <cstdlib>
#include <cassert>
#include <array>
#include <unordered_set>
#include <mutex>
struct ggml_cgraph { uint64_t uid; int nodes; };
struct rpc_dispatcher { uint64_t last_uid; std::mutex graph_mutex; std::array<std::unordered_set<uint64_t>,1> graph_uids; void graph_compute(uint32_t,const ggml_cgraph *); };
'''+body+'''
int main() {
 rpc_dispatcher dispatcher{}; ggml_cgraph graph{123,7};
 unsetenv("GGML_RPC_NO_GRAPH_CACHE"); dispatcher.graph_compute(0,&graph);
 assert(dispatcher.last_uid==123 && graph.uid==123 && graph.nodes==7);
 setenv("GGML_RPC_NO_GRAPH_CACHE","1",1); dispatcher.graph_compute(0,&graph);
 assert(dispatcher.last_uid==0 && graph.uid==123 && graph.nodes==7);
}
'''
        with tempfile.TemporaryDirectory() as directory:
            source=Path(directory)/'check.cpp'; binary=Path(directory)/'check'; source.write_text(code)
            subprocess.run(['c++','-std=c++17',str(source),'-o',str(binary)],check=True,capture_output=True)
            result=subprocess.run([str(binary)],capture_output=True)
            self.assertEqual(result.returncode,0,result.stderr.decode(errors='replace'))

    @unittest.skipUnless(shutil.which('c++'),'A C++ compiler is needed for alignment behavior checks')
    def test_staging_has_alignment_slack_without_changing_the_cpu_allocator(self):
        patched=patch_rpc_source(SOURCE)
        pieces=re.findall(r'^static (?:ggml_backend_buffer_t|ggml_backend_buffer_type_t) ggml_backend_rpc_(?:host_buffer_alloc|device_get_host_buffer_type)\([^\n]+\) \{.*?^}',patched,re.S|re.M)
        code='''#include <cstdlib>
#include <cstdint>
#include <cassert>
#include <limits>
#include <initializer_list>
#define GGML_UNUSED(x) (void)(x)
struct ggml_backend_buffer_type;
struct ggml_backend_buffer { ggml_backend_buffer_type * buft; size_t size; unsigned char * data; void * raw; };
using ggml_backend_buffer_t=ggml_backend_buffer *;
using ggml_backend_buffer_type_t=ggml_backend_buffer_type *;
using ggml_backend_dev_t=void *;
using allocator=ggml_backend_buffer_t (*)(ggml_backend_buffer_type_t,size_t);
struct ggml_backend_buffer_type { struct { allocator alloc_buffer; } iface; };
static int calls=0;
static ggml_backend_buffer_t cpu_alloc(ggml_backend_buffer_type_t t,size_t n) {
 ++calls; void * raw=std::aligned_alloc(4096,((n+8191)/4096)*4096);
 return new ggml_backend_buffer{t,n,static_cast<unsigned char *>(raw)+64,raw};
}
static ggml_backend_buffer_type cpu_type{{cpu_alloc}};
static ggml_backend_buffer_type_t ggml_backend_cpu_buffer_type() { return &cpu_type; }
static ggml_backend_buffer_t ggml_backend_buft_alloc_buffer(ggml_backend_buffer_type_t t,size_t n) { return t->iface.alloc_buffer(t,n); }
'''+ '\n'.join(pieces)+'''
int main() {
 auto * t=ggml_backend_rpc_device_get_host_buffer_type(nullptr);
 for (size_t alignment : {size_t(512),size_t(4096),size_t(65536)}) {
  const size_t read_size=65536+2*alignment;
  auto * b=ggml_backend_buft_alloc_buffer(t,read_size);
  uintptr_t ptr=reinterpret_cast<uintptr_t>(b->data),aligned=(ptr+alignment-1)&~uintptr_t(alignment-1);
  assert(aligned+read_size <= ptr+b->size);
  assert(b->buft==t && cpu_type.iface.alloc_buffer==cpu_alloc);
  std::free(b->raw); delete b;
 }
 const int before=calls;
 assert(ggml_backend_buft_alloc_buffer(t,SIZE_MAX)==nullptr && calls==before);
}
'''
        with tempfile.TemporaryDirectory() as directory:
            source=Path(directory)/'alignment.cpp'; binary=Path(directory)/'alignment'; source.write_text(code)
            compiled=subprocess.run(['c++','-std=c++17',str(source),'-o',str(binary)],capture_output=True)
            self.assertEqual(compiled.returncode,0,compiled.stderr.decode(errors='replace'))
            result=subprocess.run([str(binary)],capture_output=True)
            self.assertEqual(result.returncode,0,result.stderr.decode(errors='replace'))
