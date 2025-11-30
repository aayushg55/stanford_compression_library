#include <pybind11/pybind11.h>
#include <pybind11/stl.h>

#include "scl/fse/fse.hpp"

namespace py = pybind11;
using namespace scl::fse;

PYBIND11_MODULE(scl_fse_cpp, m) {
    m.doc() = "Spec-accurate FSE bindings";

    py::enum_<FSELevel>(m, "FSELevel")
        .value("L0_Spec", FSELevel::L0_Spec)
        .value("L1_Clean", FSELevel::L1_Clean)
        .value("L2_Tuned", FSELevel::L2_Tuned)
        .value("L3_Experimental", FSELevel::L3_Experimental);

    py::class_<FSEParams>(m, "FSEParams")
        .def(py::init<const std::vector<uint32_t>&, uint32_t, uint32_t>(),
             py::arg("counts"),
             py::arg("table_log"),
             py::arg("data_block_size_bits") = 32)
        .def_readonly("counts", &FSEParams::counts)
        .def_readonly("table_log", &FSEParams::table_log)
        .def_readonly("table_size", &FSEParams::table_size)
        .def_readonly("normalized", &FSEParams::normalized)
        .def_readonly("data_block_size_bits", &FSEParams::data_block_size_bits)
        .def_readonly("initial_state", &FSEParams::initial_state);

    py::class_<FSETables>(m, "FSETables")
        .def(py::init<const FSEParams&>());

    py::class_<EncodedBlock>(m, "EncodedBlock")
        .def_readonly("bytes", &EncodedBlock::bytes)
        .def_readonly("bit_count", &EncodedBlock::bit_count);

    py::class_<IFSEEncoder>(m, "IFSEEncoder");
    py::class_<FSEEncoderMSB, IFSEEncoder>(m, "FSEEncoder")
        .def(py::init<const FSETables&>())
        .def("encode_block",
             [](const FSEEncoderMSB& enc, const std::vector<uint8_t>& symbols) {
                 return enc.encode_block(symbols);
             });

    py::class_<DecodeResult>(m, "DecodeResult")
        .def_readonly("symbols", &DecodeResult::symbols)
        .def_readonly("bits_consumed", &DecodeResult::bits_consumed);

    py::class_<IFSEDecoder>(m, "IFSEDecoder");
    py::class_<FSEDecoderMSB, IFSEDecoder>(m, "FSEDecoder")
        .def(py::init<const FSETables&>())
        .def("decode_block",
             [](const FSEDecoderMSB& dec, const std::vector<uint8_t>& bytes) {
                 DecodeResult res = dec.decode_block(bytes.data(), bytes.size() * 8);
                 return py::make_tuple(res.symbols, res.bits_consumed);
             });
}
