; scl::fse::DecodeResult scl::fse::decode_block_impl<scl::fse::BitReaderLSB>(unsigned char const*, unsigned long, unsigned long, scl::fse::FSETables const&)
+0x00	stp                 x28, x27, [sp, #-0x60]!
+0x04	stp                 x26, x25, [sp, #0x10]
+0x08	stp                 x24, x23, [sp, #0x20]
+0x0c	stp                 x22, x21, [sp, #0x30]
+0x10	stp                 x20, x19, [sp, #0x40]
+0x14	stp                 x29, x30, [sp, #0x50]
+0x18	add                 x29, sp, #0x50
+0x1c	mov                 x20, x8
+0x20	movi.2d             v0, #0000000000000000
+0x24	stp                 q0, q0, [x8]
+0x28	ldr                 w8, [x3, #0x8]
+0x2c	cbz                 w8, "scl::fse::DecodeResult scl::fse::decode_block_impl<scl::fse::BitReaderLSB>(unsigned char const*, unsigned long, unsigned long, scl::fse::FSETables const&)+0x2cc"
+0x30	mov                 x23, x3
+0x34	mov                 x19, x2
+0x38	mov                 x21, x0
+0x3c	mov                 x10, #0x0                       ; =0
+0x40	lsr                 x11, x2, #3
+0x44	and                 x9, x2, #0x7
+0x48	add                 x12, x1, #0x7
+0x4c	lsr                 x25, x12, #3
+0x50	subs                x12, x25, x11
+0x54	csel                x12, xzr, x12, lo
+0x58	b.ls                "scl::fse::DecodeResult scl::fse::decode_block_impl<scl::fse::BitReaderLSB>(unsigned char const*, unsigned long, unsigned long, scl::fse::FSETables const&)+0xd4"
+0x5c	add                 x11, x21, x11
+0x60	ldrb                w10, [x11]
+0x64	cmp                 x12, #0x1
+0x68	b.eq                "scl::fse::DecodeResult scl::fse::decode_block_impl<scl::fse::BitReaderLSB>(unsigned char const*, unsigned long, unsigned long, scl::fse::FSETables const&)+0xd4"
+0x6c	ldrb                w13, [x11, #0x1]
+0x70	orr                 x10, x10, x13, lsl #8
+0x74	cmp                 x12, #0x2
+0x78	b.eq                "scl::fse::DecodeResult scl::fse::decode_block_impl<scl::fse::BitReaderLSB>(unsigned char const*, unsigned long, unsigned long, scl::fse::FSETables const&)+0xd4"
+0x7c	ldrb                w13, [x11, #0x2]
+0x80	orr                 x10, x10, x13, lsl #16
+0x84	cmp                 x12, #0x3
+0x88	b.eq                "scl::fse::DecodeResult scl::fse::decode_block_impl<scl::fse::BitReaderLSB>(unsigned char const*, unsigned long, unsigned long, scl::fse::FSETables const&)+0xd4"
+0x8c	ldrb                w13, [x11, #0x3]
+0x90	orr                 x10, x10, x13, lsl #24
+0x94	cmp                 x12, #0x4
+0x98	b.eq                "scl::fse::DecodeResult scl::fse::decode_block_impl<scl::fse::BitReaderLSB>(unsigned char const*, unsigned long, unsigned long, scl::fse::FSETables const&)+0xd4"
+0x9c	ldrb                w13, [x11, #0x4]
+0xa0	orr                 x10, x10, x13, lsl #32
+0xa4	cmp                 x12, #0x5
+0xa8	b.eq                "scl::fse::DecodeResult scl::fse::decode_block_impl<scl::fse::BitReaderLSB>(unsigned char const*, unsigned long, unsigned long, scl::fse::FSETables const&)+0xd4"
+0xac	ldrb                w13, [x11, #0x5]
+0xb0	orr                 x10, x10, x13, lsl #40
+0xb4	cmp                 x12, #0x6
+0xb8	b.eq                "scl::fse::DecodeResult scl::fse::decode_block_impl<scl::fse::BitReaderLSB>(unsigned char const*, unsigned long, unsigned long, scl::fse::FSETables const&)+0xd4"
+0xbc	ldrb                w13, [x11, #0x6]
+0xc0	orr                 x10, x10, x13, lsl #48
+0xc4	cmp                 x12, #0x7
+0xc8	b.eq                "scl::fse::DecodeResult scl::fse::decode_block_impl<scl::fse::BitReaderLSB>(unsigned char const*, unsigned long, unsigned long, scl::fse::FSETables const&)+0xd4"
+0xcc	ldrb                w11, [x11, #0x7]
+0xd0	orr                 x10, x10, x11, lsl #56
+0xd4	lsr                 x9, x10, x9
+0xd8	mov                 w10, #-0x1                      ; =-1
+0xdc	lsl                 w11, w10, w8
+0xe0	cmp                 w8, #0x20
+0xe4	csinv               w10, w10, w11, eq
+0xe8	str                 x8, [x20, #0x18]
+0xec	ands                w22, w10, w9
+0xf0	b.eq                "scl::fse::DecodeResult scl::fse::decode_block_impl<scl::fse::BitReaderLSB>(unsigned char const*, unsigned long, unsigned long, scl::fse::FSETables const&)+0x2cc"
+0xf4	add                 x26, x8, x19
+0xf8	ldr                 w9, [x23]
+0xfc	cbz                 w9, "scl::fse::DecodeResult scl::fse::decode_block_impl<scl::fse::BitReaderLSB>(unsigned char const*, unsigned long, unsigned long, scl::fse::FSETables const&)+0x1b0"
+0x100	mov                 x11, #0x0                       ; =0
+0x104	lsr                 x12, x26, #3
+0x108	and                 x10, x26, #0x7
+0x10c	subs                x13, x25, x12
+0x110	csel                x13, xzr, x13, lo
+0x114	b.ls                "scl::fse::DecodeResult scl::fse::decode_block_impl<scl::fse::BitReaderLSB>(unsigned char const*, unsigned long, unsigned long, scl::fse::FSETables const&)+0x190"
+0x118	add                 x12, x21, x12
+0x11c	ldrb                w11, [x12]
+0x120	cmp                 x13, #0x1
+0x124	b.eq                "scl::fse::DecodeResult scl::fse::decode_block_impl<scl::fse::BitReaderLSB>(unsigned char const*, unsigned long, unsigned long, scl::fse::FSETables const&)+0x190"
+0x128	ldrb                w14, [x12, #0x1]
+0x12c	orr                 x11, x11, x14, lsl #8
+0x130	cmp                 x13, #0x2
+0x134	b.eq                "scl::fse::DecodeResult scl::fse::decode_block_impl<scl::fse::BitReaderLSB>(unsigned char const*, unsigned long, unsigned long, scl::fse::FSETables const&)+0x190"
+0x138	ldrb                w14, [x12, #0x2]
+0x13c	orr                 x11, x11, x14, lsl #16
+0x140	cmp                 x13, #0x3
+0x144	b.eq                "scl::fse::DecodeResult scl::fse::decode_block_impl<scl::fse::BitReaderLSB>(unsigned char const*, unsigned long, unsigned long, scl::fse::FSETables const&)+0x190"
+0x148	ldrb                w14, [x12, #0x3]
+0x14c	orr                 x11, x11, x14, lsl #24
+0x150	cmp                 x13, #0x4
+0x154	b.eq                "scl::fse::DecodeResult scl::fse::decode_block_impl<scl::fse::BitReaderLSB>(unsigned char const*, unsigned long, unsigned long, scl::fse::FSETables const&)+0x190"
+0x158	ldrb                w14, [x12, #0x4]
+0x15c	orr                 x11, x11, x14, lsl #32
+0x160	cmp                 x13, #0x5
+0x164	b.eq                "scl::fse::DecodeResult scl::fse::decode_block_impl<scl::fse::BitReaderLSB>(unsigned char const*, unsigned long, unsigned long, scl::fse::FSETables const&)+0x190"
+0x168	ldrb                w14, [x12, #0x5]
+0x16c	orr                 x11, x11, x14, lsl #40
+0x170	cmp                 x13, #0x6
+0x174	b.eq                "scl::fse::DecodeResult scl::fse::decode_block_impl<scl::fse::BitReaderLSB>(unsigned char const*, unsigned long, unsigned long, scl::fse::FSETables const&)+0x190"
+0x178	ldrb                w14, [x12, #0x6]
+0x17c	orr                 x11, x11, x14, lsl #48
+0x180	cmp                 x13, #0x7
+0x184	b.eq                "scl::fse::DecodeResult scl::fse::decode_block_impl<scl::fse::BitReaderLSB>(unsigned char const*, unsigned long, unsigned long, scl::fse::FSETables const&)+0x190"
+0x188	ldrb                w12, [x12, #0x7]
+0x18c	orr                 x11, x11, x12, lsl #56
+0x190	lsr                 x10, x11, x10
+0x194	mov                 w11, #-0x1                      ; =-1
+0x198	lsl                 w12, w11, w9
+0x19c	cmp                 w9, #0x20
+0x1a0	csinv               w11, w11, w12, eq
+0x1a4	and                 w27, w11, w10
+0x1a8	add                 x26, x26, x9
+0x1ac	b                   "scl::fse::DecodeResult scl::fse::decode_block_impl<scl::fse::BitReaderLSB>(unsigned char const*, unsigned long, unsigned long, scl::fse::FSETables const&)+0x1b8"
+0x1b0	mov                 x9, #0x0                        ; =0
+0x1b4	mov                 w27, #0x0                       ; =0
+0x1b8	add                 x8, x9, x8
+0x1bc	str                 x8, [x20, #0x18]
+0x1c0	mov                 x0, x22
+0x1c4	bl                  "0x1042c9010"
+0x1c8	mov                 x24, x0
+0x1cc	add                 x28, x0, x22
+0x1d0	mov                 x1, x22
+0x1d4	bl                  "0x1042c9058"
+0x1d8	stp                 x24, x28, [x20]
+0x1dc	str                 x28, [x20, #0x10]
+0x1e0	mov                 w8, #-0x1                       ; =-1
+0x1e4	ldr                 x9, [x23, #0x30]
+0x1e8	b                   "scl::fse::DecodeResult scl::fse::decode_block_impl<scl::fse::BitReaderLSB>(unsigned char const*, unsigned long, unsigned long, scl::fse::FSETables const&)+0x220"
+0x1ec	and                 x13, x26, #0x7
+0x1f0	lsr                 x12, x12, x13
+0x1f4	lsl                 w13, w8, w11
+0x1f8	cmp                 w11, #0x20
+0x1fc	csinv               w13, w8, w13, eq
+0x200	and                 w12, w13, w12
+0x204	add                 x26, x26, x11
+0x208	ldrh                w11, [x10]
+0x20c	add                 w27, w12, w11
+0x210	ldrb                w10, [x10, #0x3]
+0x214	strb                w10, [x24], #0x1
+0x218	subs                x22, x22, #0x1
+0x21c	b.eq                "scl::fse::DecodeResult scl::fse::decode_block_impl<scl::fse::BitReaderLSB>(unsigned char const*, unsigned long, unsigned long, scl::fse::FSETables const&)+0x2c4"
+0x220	add                 x10, x9, w27, uxtw #2
+0x224	ldrb                w11, [x10, #0x2]
+0x228	cbz                 w11, "scl::fse::DecodeResult scl::fse::decode_block_impl<scl::fse::BitReaderLSB>(unsigned char const*, unsigned long, unsigned long, scl::fse::FSETables const&)+0x2bc"
+0x22c	mov                 x12, #0x0                       ; =0
+0x230	lsr                 x13, x26, #3
+0x234	subs                x14, x25, x13
+0x238	csel                x14, xzr, x14, lo
+0x23c	b.ls                "scl::fse::DecodeResult scl::fse::decode_block_impl<scl::fse::BitReaderLSB>(unsigned char const*, unsigned long, unsigned long, scl::fse::FSETables const&)+0x1ec"
+0x240	add                 x13, x21, x13
+0x244	ldrb                w12, [x13]
+0x248	cmp                 x14, #0x1
+0x24c	b.eq                "scl::fse::DecodeResult scl::fse::decode_block_impl<scl::fse::BitReaderLSB>(unsigned char const*, unsigned long, unsigned long, scl::fse::FSETables const&)+0x1ec"
+0x250	ldrb                w15, [x13, #0x1]
+0x254	orr                 x12, x12, x15, lsl #8
+0x258	cmp                 x14, #0x2
+0x25c	b.eq                "scl::fse::DecodeResult scl::fse::decode_block_impl<scl::fse::BitReaderLSB>(unsigned char const*, unsigned long, unsigned long, scl::fse::FSETables const&)+0x1ec"
+0x260	ldrb                w15, [x13, #0x2]
+0x264	orr                 x12, x12, x15, lsl #16
+0x268	cmp                 x14, #0x3
+0x26c	b.eq                "scl::fse::DecodeResult scl::fse::decode_block_impl<scl::fse::BitReaderLSB>(unsigned char const*, unsigned long, unsigned long, scl::fse::FSETables const&)+0x1ec"
+0x270	ldrb                w15, [x13, #0x3]
+0x274	orr                 x12, x12, x15, lsl #24
+0x278	cmp                 x14, #0x4
+0x27c	b.eq                "scl::fse::DecodeResult scl::fse::decode_block_impl<scl::fse::BitReaderLSB>(unsigned char const*, unsigned long, unsigned long, scl::fse::FSETables const&)+0x1ec"
+0x280	ldrb                w15, [x13, #0x4]
+0x284	orr                 x12, x12, x15, lsl #32
+0x288	cmp                 x14, #0x5
+0x28c	b.eq                "scl::fse::DecodeResult scl::fse::decode_block_impl<scl::fse::BitReaderLSB>(unsigned char const*, unsigned long, unsigned long, scl::fse::FSETables const&)+0x1ec"
+0x290	ldrb                w15, [x13, #0x5]
+0x294	orr                 x12, x12, x15, lsl #40
+0x298	cmp                 x14, #0x6
+0x29c	b.eq                "scl::fse::DecodeResult scl::fse::decode_block_impl<scl::fse::BitReaderLSB>(unsigned char const*, unsigned long, unsigned long, scl::fse::FSETables const&)+0x1ec"
+0x2a0	ldrb                w15, [x13, #0x6]
+0x2a4	orr                 x12, x12, x15, lsl #48
+0x2a8	cmp                 x14, #0x7
+0x2ac	b.eq                "scl::fse::DecodeResult scl::fse::decode_block_impl<scl::fse::BitReaderLSB>(unsigned char const*, unsigned long, unsigned long, scl::fse::FSETables const&)+0x1ec"
+0x2b0	ldrb                w13, [x13, #0x7]
+0x2b4	orr                 x12, x12, x13, lsl #56
+0x2b8	b                   "scl::fse::DecodeResult scl::fse::decode_block_impl<scl::fse::BitReaderLSB>(unsigned char const*, unsigned long, unsigned long, scl::fse::FSETables const&)+0x1ec"
+0x2bc	mov                 w12, #0x0                       ; =0
+0x2c0	b                   "scl::fse::DecodeResult scl::fse::decode_block_impl<scl::fse::BitReaderLSB>(unsigned char const*, unsigned long, unsigned long, scl::fse::FSETables const&)+0x208"
+0x2c4	sub                 x8, x26, x19
+0x2c8	str                 x8, [x20, #0x18]
+0x2cc	ldp                 x29, x30, [sp, #0x50]
+0x2d0	ldp                 x20, x19, [sp, #0x40]
+0x2d4	ldp                 x22, x21, [sp, #0x30]
+0x2d8	ldp                 x24, x23, [sp, #0x20]
+0x2dc	ldp                 x26, x25, [sp, #0x10]
+0x2e0	ldp                 x28, x27, [sp], #0x60
+0x2e4	ret