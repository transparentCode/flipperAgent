from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest

from libs.models.trendline_v2.configuration import ConfirmedExtremaPairConfig
from libs.models.trendline_v2.discovery import (
    ProviderDiagnostics,
    ProviderInput,
    ProviderReason,
    ProviderRequest,
    ProviderResult,
    ProviderStatus,
)
from libs.models.trendline_v2.discovery.provider_evidence import (
    ConfirmedExtremaPairEvidence,
    ExtremaKind,
    confirmed_extrema_anchor_id,
)
from libs.models.trendline_v2.domain import (
    AnchorRef,
    CandidateEvidence,
    LineCandidate,
    LineGeometry,
    LineRole,
)
from libs.models.trendline_v2.domain.validation import ContractValidationError
from scripts import replay_trendline_v2_causal_temporal_tracking as study


UTC = timezone.utc
BASE = datetime(2026, 5, 22, tzinfo=UTC)


# Exact external evidence tuple:
# dataset, checkpoint, prefix, provider, discovery, selection, tracking,
# candidate, selected, active, births, continuations, removals.
EXPECTED_EXTERNAL_ROWS = (
    ('btcusdt_1h', 1, '94dc07ca4a52437a0e7777d14087c11bf97cbe1cfba2705cbd77df9f847137ff', '96840d9301bb5009c75d1ebf12a8a11fc998b8e83415669fd6e827d4a3867595', '82a555b51cf9e7797c49cc345ee144c2560c7cd51653db86ec1e79143258f111', '6d527e5e70d2057b337b9d24c689790256bb94aec9be676c1efa791e5eaa6c27', '1962082e559beb95aea834dc7f2a316e126ed19a83109398f380f3c56600a3b4', 1018, 121, 121, 121, 0, 0),
    ('btcusdt_1h', 2, '00e4ae313ae68bfa1482c71ac6e861d4652899338988c5d16e7ec4e01dc012e5', '60b9807f9e94b180f2db492091297406c8c07c7ed2c357d67cb2fac2fac19182', 'b3d78f92b6f63e645fed542e62298a4e3e796d382433db28ed08eb13d6886c03', '9241487d0b9bf804de2a73b430b08b13a64c727efeb40f926c06814fa9ded187', '7cbf60f2afb43613508523e24b32e6c73ef45003f98073b7349508d11dc692fe', 1409, 165, 165, 44, 121, 0),
    ('btcusdt_1h', 3, '07cc0e9b4e39fc2be9aa06d29559deab1003e0a8eb4243dd4474f7865147c408', '2dc72700fe97538f2644d49e6a5bc629ad3fcd656a1ce6017343235c9e2ad36b', '066713eb186e3a206f92a3b8e1ea6d8ef1b4021b41909cfd635a6a6234e751f8', '0dcf9c35994985a96f40dec9ffb368a8b2c0ebba0ac98e38f3850f35564ce1ac', '70319e0518b645c004021754cd27cbb5312e3d40d6401043c614a9c989b4522b', 1805, 205, 205, 40, 165, 0),
    ('btcusdt_1h', 4, '1daee0c74f3a4a48a134d4ce60a9a89d6cdaafed797f13397d3dd3cf0caebd10', '1e5d6040d77d2ba270b4bca3c8d0f0c835a46a7fbf368ca6020b53181f850ca4', '9e2f72f26f0aae374a94d0ae691706b9a6795a895343f5feed73adf7ac740161', '280d26b7cbd812a2fa1c89f2649cbaa803bf7a966a3ba9520a862da32851681d', '6c8ca15839a0f322c15e695a043e8db33686e373eae563702778d4c01bfb8370', 2612, 253, 253, 48, 205, 0),
    ('btcusdt_1h', 5, 'b8578e88a910a740e346c1d0e24227ba19d70fb3987fdebfecb18a61f0676fc9', 'a0a5ef4097932313076b5e3df56add2bff5a47b86a1e30e0f9f968a3787bb6ae', 'a11692460a5e27eeaa1edb55591296c923bb8a57df9c25f154e8e51fadec61a0', '9d2008c1ec210353d54d0fdd4f636411d295c90c59378ba6fee2c02ad885d297', '837297052841cda2c153c4c7a20f0aee953a714dcbe7f7aa46c4249bace97868', 3155, 291, 291, 38, 253, 0),
    ('btcusdt_1h', 6, '7930eb38891515ec4839b68f2a7ed4d01d99899238dac5cd44195027047376f3', 'b1bd5ad37fc85ec6ea8a9d9b534d4f5f84720242cc9d4f4e1a17419fc0ce5857', 'cdf4403904b21b326172fc15f9c8bd60f11c79532e8a418ebab042ed37d7b5b0', 'e60c5e9de89d5845ad887a3d0afb5542e373725ff85681d742d6e0bbc6b36866', '0ca5015069dc4a60a7f095ef4942bf8c5612072046bd91ae6486cce023707a0d', 3509, 333, 333, 42, 291, 0),
    ('btcusdt_1h', 7, 'f4f5ba2658e8218ed043f366a6dc389b70d28f4a6898d51d627a267e379f2f7e', 'f9f687c468b516c44ab8b7e917aecbad10b19ff79887fbf7d80e6764a7ffc9d7', '761a14fa4b54dddfa154f116873075a7c99737d75920840907d18447141c6872', '877db6c6f0360ad96ba8a38f95ceca65ed68c6396c0a29b44be454ea01df706d', '86edbed78c470da5dfe40dce9fdd1c828402dd63282673f620a3f635b177c0a8', 3908, 373, 373, 40, 333, 0),
    ('btcusdt_1h', 8, 'dde3d8a82109e4eda6dfec8b1a128e7896dc6845bcd47bab5754eefcc79623e9', '68975843daddef910a08e390f475fdfc20fe784637767c92f4b1ff7d7cd12f9e', '2506622d81c90004940d519625a849633471b2824687243aa12cffc238ed8c9f', 'ed7959f4591e749f087d5dbb83c74df2a31125c51c2c77303068553e2f1190ab', 'ccca082b51b88e23671b120eec5161232074d9135a5f2fb6142da8094906c763', 4343, 422, 422, 49, 373, 0),
    ('btcusdt_4h', 1, '958be974559fcbca547ddbe22090dad2870f877715136d839e4c2c1a7554c6fa', 'a4903da8e4a140c7ee89a1c031f5bd9c5fef646151059c68fcc0863349846e60', '4063654d048df44896317364c3a2b4eaa9e5a1fdb63a2680ef17beb844382edc', '9d2226d5ecf4513e582078cc36086555c194d2ceafbe65ec85ac6fae5a8222be', '8a102ac42416a2d930531fc17deea5f94b78cb21357ab98f76654086168c09bb', 104, 26, 26, 26, 0, 0),
    ('btcusdt_4h', 2, 'a4d6eac4d163b38076d946d324e21d106801cfd98fcee38cbfe49b7e7acc0684', '02874f135329c050da3bd6b3402c921f34fc7a2d668fd957f6788fc379153559', '11a06f9766fb68550b8564dfd0f4baadb49ee0d89cebdde33e8d422aad9e4e98', 'a1c6ca521ceb4c985f72cf06c7f16847a47156ffbc4ab9c40f995d18c669256b', 'f2f391a4c9ffe1547f11dcf3f9405ed88ce258e6bac96aeb3bd81fca23b26e23', 171, 36, 36, 10, 26, 0),
    ('btcusdt_4h', 3, 'e0a955fd59c4537df177540b75efd8b6509b7c4d18d197df4998220e42a48947', '105be28ab81f8158eabfde71af250ba5499b369d3af0922e0a21f003ebf3c769', 'ea66dcc93281355e25150cd557d4c84e72557d6378001b6a7f023f408395d5b1', '9c24353a17b2da85a41e71cd8a8b23f715ee7f066ed128c85ede04984c69540a', '2b397a622ca4a28312c13026b77234edbf3f54ef02aa0f2c47b6ac137fae4854', 220, 47, 47, 11, 36, 0),
    ('btcusdt_4h', 4, '8e346910762f8fe3031d297abb9b70d89142078952882d0a15326fc8cb6663ec', '35867a264b7781b381e92238746d23b9728b5d7ba4cfdd4c59fadb2d8ab338a3', '428c18e76dd9e68ff0e40d8066cf1fd6a130dfc54c7cc67c18ea280b6fcfa61f', '0ab48baac95a2ec353d7db2b9cc39e735505e9d983c545461ecad089e460557c', '62a238a765dfbbdf7d31f4441da21a0d193807ae7d053d3c925632f064f47473', 319, 61, 61, 14, 47, 0),
    ('btcusdt_4h', 5, 'c01303a282f2b43cdeed103ab86d342a789f64cd2021be5f54cabb54f631f734', 'a362d90242f072d7a23d3b71a173540ede54435a92d89db829e84e217f26fbc7', '0acbe1918ed3e60f00411d5a6476ca42f8c0642d79482c1cde6da31262d858d1', '6d098188858f7392d5b40f4e91443cae225d6fe69debf6f1bc44b53395b64555', '2717951a21090231be5e5f4483a3813cda8469021faafa52a81f66144194b947', 424, 74, 74, 13, 61, 0),
    ('btcusdt_4h', 6, 'b9e4df463f581e3f908b1065bb62cefea8e0eea1cc6a817ca76853d4078aa6fd', '367661b37df401a5f9debefdb66cb968ed27504e011f4cdc2d8fe267433725cf', 'b040b3173f8ef51c05a9d5b3f7104a446c4688987896d14dc7168c927dfb8bc7', 'e316c2fe5e7750e57fd1abcbccf6b00bfa6adf59469e8879177fc7298a7021a9', '1017d290f3126bca6dd40b1bbc54228f2c7c11552a5fcec56e8de7c40d301f91', 509, 86, 86, 12, 74, 0),
    ('btcusdt_4h', 7, '40f3825a92c25a04faaf14da7c825d8b3629fd15cd4d6b72fa0a104c21680985', '23286130aee0874f98b3f178ebbdd82331e57e2b7145a7d062d886d179a11dca', '838490b61ef95dc151745b24664e0f3058d3b7f81670a490b7855f7159d13d09', 'cf88f371075da1f45fabee611a634b871acc290822d051050f25678b9e081dce', '6adacac0062d66b7be6e1613842a351c57acc7a35c7c566dd9d9ba20fd8a5905', 609, 96, 96, 10, 86, 0),
    ('btcusdt_4h', 8, '2de51ce8f76920b92269fe94c78efb636944d4c804d5dd723875903df5bc8aa8', 'ea53abf260b3b19966140bcb1157c4924b14c43d69307917e59fd95c8f973824', 'ac7e968c474e12d39c68bbc0c394669f60c0f3ff63276f5c439c8bb35dff3151', '31330b3c58cb0ee8f33979683c080bc881d2d04b8ea76bbe18cacbdce2eb67da', '64a74c3172d616015a35d924a4a89c31de0784ba7ce44c9609ec66352497dd6b', 673, 106, 106, 10, 96, 0),
    ('ethusdt_1h', 1, '797bb3cbb484e047dad5318ab5f2bd7cdb8db965d19d205fe3b0472dfd850670', 'cadc34c62d6f2bf5972b0219df72eb907845e5a829364727b58e3202a30a1cb4', 'eb5d326aaacdb8c1989df89aca3772506ab08cfad989336c31f8102a277f1980', '58165f59d7d329be837daab5054cbd981c1fde46d785631e665f32c94348175e', 'dd1be3e0ed75d0bddf4f39b4218f5e6c9c883312772d6ddb77a88176becc55d4', 917, 131, 131, 131, 0, 0),
    ('ethusdt_1h', 2, '8d11e7adf48bde6b4154c7bca691e509c1b2831c8601dde8ad1a1ee5b53e86b5', 'e68209022319f1fbc4ae93eeb0b48c154afb771eaa04c5f82c511c58fe98bd60', 'ff1302e31698623fc0581cbae7cd0ddd461b4a3341a14ae24581649a583b272a', 'd9579ddbd052544d83eadde67560e21b6d88a8393f2177175b6afb02c3816eed', '975089133c532ddf52d1953b8791ceb4cd9e7efa4371d4d1aac2e497a5bfd6c2', 1421, 170, 170, 39, 131, 0),
    ('ethusdt_1h', 3, '93637e37e5f8096f792f6e8ab8c1a87f28eb6e36aab67e08a4b82667add4fd40', 'cb1539576532a486b6fe6cc3e78622c778831da708a13862d96343386d349a69', '32667a1b4868ae69687f11f300245a23ca690f621b47146bb17b112beafb49ac', '2416316e1c5a1e31a7a7ffe3d4a9b5c482b4d8a0a3ea05d6b71713345430f453', 'a0ab98c4b3340d666bb0e33c443d8b7347b15f08f6eb087b5456fb428796c97d', 1915, 213, 213, 43, 170, 0),
    ('ethusdt_1h', 4, 'a4b1e02017927d03ee52acbda72582e6f284c548b898740b2ee1ba7c40f28f3e', '2173ad3bc7fbe9bd607fd7d10872b4f56557e278ce78a63c32971a6c2224927e', '5a3dde28132114347510c0b2f9022232a4608d05b408f7f37cd6f949811f7820', 'b9a4da84354c70e4aefef17324680873416d442aa77893e914bc2bd2585d936c', '8713a8a0247ae9df638bb838a4c7965c523c258110ab66f4b9f34a17b3601bbb', 2549, 263, 263, 50, 213, 0),
    ('ethusdt_1h', 5, '99a03e99ba897b12ce940a54659d6285e125b53c84d4d0f63e0e98277bf7eb00', '55babc5478383c73206ee78b5aa2d96a21b6b063e025130b62f4b52ac995fb04', '9cea92a312e05e1b16cb78b2bb8156c31929d415541c8a8ad01b4487dd03f439', 'dec6db3eaa7b6c7085725a212d75704e051764ad5cfcfb719a90e382d3b15739', '80904e7aa7abfa525058fc66dd12311cd614550df81d2eca3439d9a881c5d3e9', 2990, 303, 303, 40, 263, 0),
    ('ethusdt_1h', 6, 'faad313b551595e07cbb868a20f5b35a93bb447e45df4d32be3f7b401389e3a6', '712c46a2ec617f2b6407f7c21083803f1a780e11399cbca21b51c076539ce7f9', '9c7ca6bbdc619aa66bf69efc831899bb88fd18a16facc3387ff383cf79c80a6c', 'c38572f895e2d7463dcf1c8b4cdfbc352ebd1399888dda8cddbf00c1c07ca258', '530e654acd50be48e1c3818d93b710500c5cd054f78ccc32a5fc1e4ae45832d3', 3494, 347, 347, 44, 303, 0),
    ('ethusdt_1h', 7, 'f2848f3ee25cd9bacb624bd96a0f41aabf6438cc493c0e03d2ccf007f56afd6e', '0f721d0a10d8bc49b1dffb00afad66d4674c04875260381bf3857294628834d0', '1b8a41458bab405e6ec8475afaa08ad9304ae9a7984c15c48e7f2a5d2235f93e', '3a082d9de8b4131bfababad2bc4931d53d41af7e7636b45c34a7ec8306fd67b8', '31fcec08b76ae4504ec261e5b87501b2557234355df8d5426b390e582526b507', 3864, 383, 383, 36, 347, 0),
    ('ethusdt_1h', 8, '483d29e4aa2b32d85d00f8a58f956f84dfbf3ba14f6e80b80210968e85424469', 'b028dd306fd2131c2752f348847c65c3212060e9eb0b80e637bc84f021a66b77', 'ee08d3b89a53897634bb6ec15803e3298dd7fe30dfb0b41493f5ea92c03d3628', '7178dedceef1b0c97b99777a40b07dad808942330902edd093f83d9cd1ec812b', '1aa785612831815e9be0973829e76c6fe917d3ed39b0c91308018a5cc3052c02', 4264, 433, 433, 50, 383, 0),
    ('ethusdt_4h', 1, '5cb8860016758a838a731e9d92013b9925260453fe9e3f96baee349ea674d4e7', '4fecfe2bcc8d1bee7c9be10466fa11622f1006e16ac2e1ff6cde88915e7940b9', '9391eaf47b7bd747631c09bc86b7e16036d212f20289cbb39c07a9a6e2663189', 'be48bcaa3d5f18b3e173a0f61cc7702cadfad0f46dc0b874ac77c35f70eb323c', '3dd0a4f80a3d32d99ffba98629b562f11e0b0da7ee94989fe9fb04df40478ad8', 107, 28, 28, 28, 0, 0),
    ('ethusdt_4h', 2, '583a7c06ea6be5365322e2f67480d9ed7ae1c6e09dc8bc98eb28c52b09ae4d6f', 'c802c7480bc5917946d360d981b4ba2029c67e81fe4377292671961a05206524', '4549d3a49cb313dc035196a5733eab67e4e60402b5dac322aad4d72e86fdb50e', '0044e7141e2fd2de0465adec108aab9b1652ffa7fd3a1e17e1e9b509e0ceb9c3', '1cd256c6976d0cde120f99c127f798c7d44fc4c2399d97ae7b3ff6727ed4e764', 190, 37, 37, 9, 28, 0),
    ('ethusdt_4h', 3, '06aea57a605af0e3a4575221c7555a881a5f921a1f3a9fda9e486935b271de8a', 'a8fbb746ca770785b4716bad58c86145e59a8e685aee1f2fe44c174754687725', 'b2f2ff36cdfecaa59beaa3c52669982c84848734e4c4007abb7f45044f810763', '5f14f8f3deafd1c38ff1e9660d572efb82166461b2fd2347817d67fb1567e118', '9e091b9da340e0aaf0605dc105c5bf13a57cbbe905d62133ec3ea3c4ab34d7ec', 248, 49, 49, 12, 37, 0),
    ('ethusdt_4h', 4, '7a3dd5af6a85bfa2ada840f385e4b509d176a40d0b0871e7f127683dd778576c', 'b70796c8c22a83eabc5d539faf07fe5a4a4d9800fb11b2eb0d0cbeeff2b636f3', '76f81590826d54e9dc83e330417d1a0a6b7dc548db2efe607b7335456b76c70e', 'ee12a638b19e51eac0cbec9753d13add084e067f43c6e4b62b85b658b89db33d', '7f2d26aff90693fe547c2bd0ea4c8fe60a792869de33f0682a09b6ff7ad666f7', 339, 61, 61, 12, 49, 0),
    ('ethusdt_4h', 5, 'aee65d2d4ff7965a52f9d3df5c991a5617c40ca53b8827475ca8026359f50ccf', '33c6ade67b7f8d679f295b709b309d7a1b2651fb4e8aa3e541be19adf10b5dff', '086f392f3a6a0dc9ea481118b00f8b1fffa6420b6d7327d421de220bccfc7f9f', 'd54f78f7a43c9c67a04bc26641fc113b853a2dfbf0a1efaf23aa84aa6615d38a', 'deffd82206aee50ad64af3542e7c560617ce8c355d88fa7d778eff85c80a4527', 417, 73, 73, 12, 61, 0),
    ('ethusdt_4h', 6, '88f20e100d087991529ca19ebf005fbed8e1d74e8766e8be96d3375e2f42a34c', '6bf206653c2a7fad0a3363d3091207669f64776e6f35ec2f94332610da30fa2b', '26bbeb5d4532840ff4075bcf74353f9f9195c06f7fbc1fb7bf83c402c2652f01', 'cd25c4f393caab2e9d5c25d249fc76ee255b9e930078ffb8bec1037f163fd74c', 'bcc379f8808757b6e61a8e414c733dbf4d06ea9a3b4dbef5b0ac6d4de2ec1033', 536, 87, 87, 14, 73, 0),
    ('ethusdt_4h', 7, '7503a1704192bdedbcf849c1a1ca5a9808351e0994e95d047a5e3c5254d62975', '866ff1d3b86e05ab2a4dd848f7793cc712619ab3a552886977c784538d7a7af7', 'e7ba8dd044acee69b32a6592ae25b20037ab1287dbaf01e37e4fd5d39da8e721', '3f152791b4bee87283cef8554a581020d9563bd89068fbb3c2872eba78a0b0ff', '5e8e9cf46d48aea8bb43789b9dd0b1d5a6461ecbbda53a697ea642b8447ea30f', 662, 98, 98, 11, 87, 0),
    ('ethusdt_4h', 8, '35965d4fe6b90298340a130063596011b3e0bcbff26463d68525f6097a762239', 'eaf1f8046f53c1316d7b3d99d5f039698c2d2f02ee7aa467d3fbf37e88dd33ca', '25ba95a404aa74e5eae9c9c040c065e35d159b43b80dd38591d7ee00f75fbb93', 'f9c48aec092b623b89175e56888f88049fb652d75c62da56005d044a16070f56', 'ca731a982f856408f374b189927e83ac5e69c3c1d60109e7f04b7ec761ece57c', 721, 109, 109, 11, 98, 0),
    ('suiusdt_1h', 1, '2229aff6a39427bfc1c4d1887ba657f29ec9560884460c3eea58dc8b4e908962', '9c2e410fdce480703004ef2a2fca6666b1b557c3bacba3bde19081dd17bd59e3', 'e95265cb2284ee1a94724301694330609be5aad405cce5b8779cbdd23f3c6c65', '6a70f2090978992cbcd083b6eaf7588ef23bc7dee602eddc8cf1dadcc60698cb', '7ab6a65c3228146c0e1b761e0e7b74ce8d378631a9e314e7786088a367dad680', 926, 135, 135, 135, 0, 0),
    ('suiusdt_1h', 2, '55b601b6fb67be5002f4ab9bd4efa3ce50abbb68e5e350f67140bab040cc3aae', '4fa0f422e33f230cf2cb6d23511da23304430a301f4452580f406cc862b3754f', '76ec5c474b7782a59825605f3c52352e7ace3f772aa015305a362394a00ccfc5', '2c31816b553556ea7afd8886cd8c194bf4ffb5a63f388599acdc72769b60d6b9', '932068483fff8c13f4282fba013f2c7e6607370fab9c9451899fc03a36638782', 1369, 181, 181, 46, 135, 0),
    ('suiusdt_1h', 3, 'e37971ebe98581285e5530701117bc99c7fa38f923015a0c0510a45a2f39957d', '33b796d325d3ad956c76da4aac54751879c9526debc9f6b2e3849c2fdee257e3', 'd991a396993ce25a0e7f59c66173cca3dcf1baf9c6a6e60da75cf35be842f25c', 'c7376156f05c593cccfb5b3ef7c73c024baacfc165c7711e6c25f7de3a3fc172', 'd9aee3ec9fe57d8c2d13d3977c876b0aa884901073ddb9e0b23d66f02a33ec66', 1980, 226, 226, 45, 181, 0),
    ('suiusdt_1h', 4, '3e0bedcafbeb07354da03aecf8e3cba743e312ac209b48f6f05b8d07d52354ec', '3491823311a158ded65196d21654d25fbd7e80fe2240f23fa8d2b3ce42df6f57', 'cbb8f3deb7c8ed0a84687fdbdae81679251609b878826a7c54f3efb7d82c264d', '697b623efa1ad777d752bd863f2dea98626d663819ec0cdaaf9a76fea79f4d3f', 'd223d9205540efb3bce2ad356d803b3b81b115dca642b516f9de69f7e3107a1e', 2686, 271, 271, 45, 226, 0),
    ('suiusdt_1h', 5, '50decd16dd546c7dce810320cdbebf4b25233ae6673e723ac95f9ac264135044', '0ab861fc3ff2023d61320a3af4931990b3cae00d3d56a4c8ad561b61d2debd7f', 'e0708f815a81f416a43bdc1af13b671987f1b742733e534aed9b555005779923', 'dec87b6ec1728834f759da950e0fb005b94cd386c2238e1bcd3866c3ff980dea', '7097ea0c313b83343d0fad23d9b09c722aa78a57127b8494596d92f1f7c71f09', 3253, 309, 309, 38, 271, 0),
    ('suiusdt_1h', 6, 'ee66493b762aab6f5f4ebee054e545ac07fa8fceeae8271c9f80a7638b447546', 'edea20189406e18eabbe6763e4186e2e01c95558f996c0b5bf375cb0af64f5ff', '2881f31e4099ab6d3778dd7f398fff3ef891e636fe91c30e574e2a6d4943228d', 'aad141e21473fe37123f7274cf902a3be8b91b25002e8289641e6be117c6a55b', 'a9bba46ef8c5a4ad7b3ed9be7a860f4a4b3af124f4a11f547a88d3b56fed3ad7', 3675, 350, 350, 41, 309, 0),
    ('suiusdt_1h', 7, '47640ced26f1dbdc8d34fecb2a6c7124b2bd1d8f4e2b8b8c6d84eca34ce373e7', '9b6373c6ba1d366ab6887f07e3860c1ff54a0046b370be48eed809bf31b68564', 'cade122a436cfa67f9406e3267006f063c58e86a3a94f56814c789deecd31912', 'f84df8f9b4f2d23fb9c1c0c57b71e967dab2aaca5b9c01da60be96e6d3a8f2d7', 'ab60f943d18dada4ad9b2d452a54a66ecc07318339431cf5f31b2037ec1dfa01', 3964, 387, 387, 37, 350, 0),
    ('suiusdt_1h', 8, '713f24aa59bb0d8f9dbb4040cdbd56fa89c1890c263d9b9c6bc72c3c669679ae', 'e00fd1762260dbcd3f58b327599fc06e09a8b0a43d39c09d29864dcd739f9e0f', 'c6d5d93d0a106a9cbeff5a1ee92b65abc81992a6dce083600e9dc6368ddf0d95', 'd2a762fb7ff6c6e1dba2df9fdba877a00511678634c36cab7f75213ac02702db', '018dc6f9219745a338a6b36b1fb4785a78c02ca18caef9c82880169f34274661', 4410, 437, 437, 50, 387, 0),
    ('suiusdt_4h', 1, '93f552c79dc613c9238ecd6c1aed1b49002a706de106e379d7d110ea98600784', '9d34ddbcc41e8eaf775a969c9239b9303843beaa981dfc8d263bc2e03d499775', 'f67ca8467ccf6835b62144a355a26af3920c84a90ec9a59532746b8ca753ef32', 'bffba59b2e191b726b9a5143c327d5abbbcf419951b6f54ac220941a32b5f2f0', '32263024f7d470d5c22f04f20df16574cbf67728d461b0fa39991b0a49b1982d', 94, 27, 27, 27, 0, 0),
    ('suiusdt_4h', 2, '38c294dacbdd6007810b02b84bf2fe2df8947d957d5ab3deecbb7ceeac8f55a5', '966c8597ae3b6ca09ca70d520798c78e33cf2c875133733371f3088028b312a4', 'abbe42d6797b53cfa6e35b4d36d9ba32df0ece969998e9d54747427060682125', '29b23540a1ac7e2a1759a0117e2fe9dfdcf80ddbe7fe162a5dbc18ac82869a51', '3538e294cb1fa4fd85046ef97d83d53c465ea95eae777d1d1809a1d49ebe7ef7', 178, 37, 37, 10, 27, 0),
    ('suiusdt_4h', 3, 'c28b2dc1aa78dc9556b9b80275433d2d23bfaa5c1f1643bc2fe990942a099a71', '0da32caba6f2db6a84f6938bb55dbc9519e4652288a2059834aad655298ce6b1', '9e0292272855ab67da1576425afb656db4a760da657bab92a75a01ccf636f535', '759703b95159edfac872b16c066563d4fa8db0f9fcdeede8de64c15b1148a91f', 'e0a7ee35717adf0a40093046994a88f486643c250686aea4ca7f688db27e4e3b', 317, 51, 51, 14, 37, 0),
    ('suiusdt_4h', 4, '4e23a8cc3ac3c9b9511e098c626c42158c2abd503d18e630ff26f51e875a808a', 'a4675d97cbd4413ec05ba6c291609c3a7b93e9420747ec3e214699246b6bc82d', 'f30c853f584a5d87d3cfaaa948e39d93a8a3019241a0850c3cbeffe13f681aa4', '7972cde6a4d4fc127c9bc459d9c51ef38e55e340ba372135b54249059cfd7bfa', 'b332040d6cc312c2e5d564c8518da49921a9ec6be5883fb82957f927ea14f833', 456, 63, 63, 12, 51, 0),
    ('suiusdt_4h', 5, 'bf749719bb9d945f4c227d8b8e1228a7e9a5fadbd5514cc552e8f1ca2006a40f', '942269e59a9bee89c5786088cec045d5318d7ad3653c7b5b70423f669ab3058b', '283654d1ccea2fd7632a313552852f942f58bf7a3d77accc1e64632276596305', '9c29bdcfcd84f7cd2353b7379ee635b61b01b8df2c1c45d6974dab238f8f080f', '10f55fcb0dbc10cb6d0aa17cc059723065d01c8cdf4656aac180e241a1d2d6f5', 553, 72, 72, 9, 63, 0),
    ('suiusdt_4h', 6, '65f4e11d93fda728d5909c864acb74746b938f625e2011d90a7f84afbaa80f4d', '38002a08554f9cc9d73e3e76d1503205e62e23d0f7e6a6f24f56eea58f01adc0', 'cdc5aa5b894c419d2169f2bde5cbbccff9d961c0804327c4403e41a1e572ad2b', '23991df6732ba965c2729d45838298939fbfa6c64984ee6c2b2c939345286b81', '2aefe0d674b6f5220c699846d7f100ea6b12fee915cadf18a9cdb311d73ec85c', 648, 85, 85, 13, 72, 0),
    ('suiusdt_4h', 7, '1f4d872c815c1e935cc331f6e5cbe7de47977d018d4a9f23a232e6b42441443a', 'b7cbe1bbb5991c0c3047a2dad4f7c4db00c530f5041ad418fc62a43197682108', 'd6aa349a80cca6148fa408b0b11c3e7d0a9a9bd1661fa8b07e4b385449224900', 'a867ea8ee2ae9c4a167c23ffc1adcc01bda7e2cbadebed07142a75d2f65d8cb8', '5e5922470dcd6881f6e07a733bf084b4103091c9ec1930c9b0a7e4be29dd678b', 775, 100, 100, 15, 85, 0),
    ('suiusdt_4h', 8, '7a43ce7b5b8489e46edebe61a32144046c2309387a1998077f4ba2d08214cfae', '0f9b709398b4dfbdf3e078bc041e413afb88590defb09fe6a7f9efb1722734f8', '32931d377b02d19cf3ebfe684327969e815bdced6eb60cef706359c896fb9a7a', 'c2175d14d052f8893612508e5c23a66c60322d824191873e6a521da830909b6b', '86c969fb59ee22b7f2d3b28d8814a4a1c7ebae9ae2c01c64c7d0d18633d71b0c', 876, 112, 112, 12, 100, 0),
)


def _synthetic_input(timeframe: str) -> ProviderInput:
    interval = study.INTERVAL_SECONDS[timeframe]
    row_count = 960 if timeframe == "1h" else 240
    timestamps = tuple(
        int((BASE + timedelta(seconds=interval * index)).timestamp() * 1_000_000_000)
        for index in range(row_count)
    )
    open_values = tuple(100.0 for _ in range(row_count))
    close_values = tuple(100.0 for _ in range(row_count))
    highs = tuple(110.0 if index % 16 == 0 else 100.0 for index in range(row_count))
    lows = tuple(90.0 if index % 16 == 8 else 100.0 for index in range(row_count))
    return ProviderInput(
        asset="BTCUSDT",
        timeframe=timeframe,
        observed_at=datetime(2026, 7, 1, tzinfo=UTC),
        confirmed_through=datetime(2026, 7, 1, tzinfo=UTC),
        timestamps=timestamps,
        open=open_values,
        high=highs,
        low=lows,
        close=close_values,
        volume=tuple(1.0 for _ in range(row_count)),
    )


def _synthetic_datasets() -> tuple[study.ReplayDataset, ...]:
    result = []
    for order, dataset_id in enumerate(study.DATASET_ORDER, start=1):
        asset, timeframe = study.DATASET_MARKET[dataset_id]
        source = _synthetic_input(timeframe)
        result.append(
            study.ReplayDataset(
                dataset_id=dataset_id,
                asset=asset,
                timeframe=timeframe,
                full_input=ProviderInput(
                    asset=asset,
                    timeframe=timeframe,
                    observed_at=source.observed_at,
                    confirmed_through=source.confirmed_through,
                    timestamps=source.timestamps,
                    open=source.open,
                    high=source.high,
                    low=source.low,
                    close=source.close,
                    volume=source.volume,
                ),
                request_order=order,
            )
        )
    return tuple(result)


def _deterministic_provider(frame, *, config, provider_config):
    """Small injected provider used by hermetic replay tests."""

    arrays = frame.arrays()
    interval = study.INTERVAL_SECONDS[frame.timeframe]
    specs = (
        (LineRole.SUPPORT, ExtremaKind.LOW, (8, 24), 90.0),
        (LineRole.RESISTANCE, ExtremaKind.HIGH, (16, 32), 110.0),
    )
    candidates = []
    evidence = []
    for role, kind, (first, second), price in specs:
        confirmation_positions = (first + 1, second + 1)
        anchors = []
        for source_position, confirmation_position in zip(
            (first, second), confirmation_positions
        ):
            pivot_time = datetime.fromtimestamp(
                arrays.timestamps[source_position] / 1_000_000_000, tz=UTC
            )
            confirmation_time = datetime.fromtimestamp(
                arrays.timestamps[confirmation_position] / 1_000_000_000, tz=UTC
            )
            anchor_id = confirmed_extrema_anchor_id(
                asset=frame.asset,
                timeframe=frame.timeframe,
                extrema_kind=kind,
                source_timestamp=pivot_time,
                confirmation_timestamp=confirmation_time,
                source_price=price,
            )
            anchors.append(
                AnchorRef(
                    anchor_id=anchor_id,
                    pivot_time=pivot_time,
                    confirmation_time=confirmation_time,
                    price=price,
                )
            )
        candidate = LineCandidate.create(
            asset=frame.asset,
            timeframe=frame.timeframe,
            role=role,
            geometry=LineGeometry(
                anchors[0].pivot_time,
                anchors[1].pivot_time,
                price,
                price,
            ),
            anchors=tuple(anchors),
            evidence=CandidateEvidence(
                anchor_count=2,
                distinct_anchor_timestamps=2,
                anchor_span_seconds=float(second - first) * interval,
            ),
            observed_at=frame.observed_at,
            provider_name=provider_config.provider_name,
            provider_version=provider_config.provider_version,
        )
        candidates.append(candidate)
        evidence.append(
            ConfirmedExtremaPairEvidence(
                candidate_id=candidate.candidate_id,
                extrema_kind=kind,
                anchor_source_positions=(first, second),
                confirmation_positions=confirmation_positions,
                validated_intermediate_count=second - first - 1,
                body_violation_count=0,
            )
        )
    request = ProviderRequest(
        input_data=ProviderInput(
            asset=frame.asset,
            timeframe=frame.timeframe,
            observed_at=frame.observed_at,
            confirmed_through=frame.confirmed_through,
            timestamps=tuple(int(value) for value in arrays.timestamps),
            open=tuple(float(value) for value in arrays.open),
            high=tuple(float(value) for value in arrays.high),
            low=tuple(float(value) for value in arrays.low),
            close=tuple(float(value) for value in arrays.close),
            volume=tuple(float(value) for value in arrays.volume),
        ),
        config=config,
        provider_config=provider_config,
    )
    return ProviderResult(
        provider_name=provider_config.provider_name,
        provider_version=provider_config.provider_version,
        request=request,
        status=ProviderStatus.SUCCESS,
        candidates=tuple(candidates),
        evidence=tuple(evidence),
        diagnostics=ProviderDiagnostics(
            candidate_count=len(candidates), input_row_count=request.input_data.row_count
        ),
    )


def test_checkpoint_contract_and_execution_order_are_fixed() -> None:
    contract = study._checkpoint_contract()
    assert contract["checkpoint_contract_id"] == study.CHECKPOINT_CONTRACT_ID
    assert (
        study.CHECKPOINT_CONTRACT_ID
        == "01e38027a396a03730bccf6479d4cc4ece4a4391d35b32fa13ce94aef01d22b5"
    )
    assert contract["identity_payload"] == study._checkpoint_contract_identity_payload()
    assert contract["namespace"] == "trendline_v2_phase_10b_checkpoint_contract"
    assert contract["dataset_order"] == list(study.DATASET_ORDER)
    assert [item["checkpoint_index"] for item in contract["checkpoints"]] == list(range(1, 9))
    assert [item["rows_by_timeframe"]["1h"] for item in contract["checkpoints"]] == [
        288,
        384,
        480,
        576,
        672,
        768,
        864,
        960,
    ]
    assert [item["rows_by_timeframe"]["4h"] for item in contract["checkpoints"]] == [
        72,
        96,
        120,
        144,
        168,
        192,
        216,
        240,
    ]


def test_checkpoint_contract_identity_changes_with_any_owned_input() -> None:
    base = study._checkpoint_contract_identity_payload_for(
        checkpoints=study.CHECKPOINTS,
        dataset_order=study.DATASET_ORDER,
        boundary_rule=study.CHECKPOINT_BOUNDARY_RULE,
    )

    def identity(payload: object) -> str:
        return study.deterministic_hash(study.CHECKPOINT_NAMESPACE, payload)

    changed_date = list(study.CHECKPOINTS)
    changed_date[0] = study.CheckpointSpec(
        1,
        datetime(2026, 6, 4, tzinfo=UTC),
        {"1h": 288, "4h": 72},
    )
    changed_rows = list(study.CHECKPOINTS)
    changed_rows[0] = study.CheckpointSpec(
        1,
        study.CHECKPOINTS[0].observed_at,
        {"1h": 287, "4h": 72},
    )
    assert identity(base) == study.CHECKPOINT_CONTRACT_ID
    assert identity(
        study._checkpoint_contract_identity_payload_for(
            checkpoints=tuple(changed_date),
            dataset_order=study.DATASET_ORDER,
            boundary_rule=study.CHECKPOINT_BOUNDARY_RULE,
        )
    ) != study.CHECKPOINT_CONTRACT_ID
    assert identity(
        study._checkpoint_contract_identity_payload_for(
            checkpoints=tuple(changed_rows),
            dataset_order=study.DATASET_ORDER,
            boundary_rule=study.CHECKPOINT_BOUNDARY_RULE,
        )
    ) != study.CHECKPOINT_CONTRACT_ID
    assert identity(
        study._checkpoint_contract_identity_payload_for(
            checkpoints=study.CHECKPOINTS,
            dataset_order=tuple(reversed(study.DATASET_ORDER)),
            boundary_rule=study.CHECKPOINT_BOUNDARY_RULE,
        )
    ) != study.CHECKPOINT_CONTRACT_ID
    assert identity(
        study._checkpoint_contract_identity_payload_for(
            checkpoints=study.CHECKPOINTS,
            dataset_order=study.DATASET_ORDER,
            boundary_rule="include source rows with timestamp <= checkpoint",
        )
    ) != study.CHECKPOINT_CONTRACT_ID


def test_checkpoint_contract_rejects_stale_expected_identity(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        study,
        "CHECKPOINT_CONTRACT_EXPECTED_ID",
        study.SUPERSEDED_CHECKPOINT_CONTRACT_ID,
    )
    with pytest.raises(study.ReplayStudyError, match="checkpoint contract identity drift"):
        study._checkpoint_contract_id()


def test_prefix_is_strictly_causal_and_future_mutation_is_inert() -> None:
    dataset = _synthetic_datasets()[0]
    first = study._prefix_input(dataset, study.CHECKPOINTS[0])
    mutated = list(dataset.full_input.high)
    mutated[-1] = 999.0
    future_dataset = study.ReplayDataset(
        dataset_id=dataset.dataset_id,
        asset=dataset.asset,
        timeframe=dataset.timeframe,
        full_input=ProviderInput(
            asset=dataset.asset,
            timeframe=dataset.timeframe,
            observed_at=dataset.full_input.observed_at,
            confirmed_through=dataset.full_input.confirmed_through,
            timestamps=dataset.full_input.timestamps,
            open=dataset.full_input.open,
            low=dataset.full_input.low,
            close=dataset.full_input.close,
            high=tuple(mutated),
            volume=dataset.full_input.volume,
        ),
        request_order=dataset.request_order,
    )
    second = study._prefix_input(future_dataset, study.CHECKPOINTS[0])
    assert first.to_dict() == second.to_dict()
    assert first.row_count == 288
    assert first.observed_at == study.CHECKPOINTS[0].observed_at
    assert first.confirmed_through == study.CHECKPOINTS[0].observed_at
    assert first.timestamps[-1] < int(first.observed_at.timestamp() * 1_000_000_000)


def test_prefix_id_advances_at_every_checkpoint() -> None:
    dataset = _synthetic_datasets()[0]
    prefixes = tuple(study._prefix_input(dataset, item) for item in study.CHECKPOINTS)
    assert len({item.input_identity for item in prefixes}) == 8
    assert [item.row_count for item in prefixes] == [288, 384, 480, 576, 672, 768, 864, 960]


def test_fixed_configuration_identity_and_policy_bindings() -> None:
    config, provider_config, selection, tracking = study._fixed_configuration()
    assert config.semantic_hash == study.FOUNDATION_CONFIG_ID
    assert provider_config.semantic_hash == study.PROVIDER_CONFIG_ID
    assert provider_config.provider_contract_identity == study.PROVIDER_CONTRACT_ID
    assert selection.policy_identity == study.SELECTION_POLICY_ID
    assert tracking.policy_identity == study.TRACKING_POLICY_ID


def test_replay_executes_exactly_48_calls_in_dataset_major_order() -> None:
    config, provider_config, selection, tracking = study._fixed_configuration()
    calls: list[tuple[str, datetime]] = []

    def provider(frame, *, config, provider_config):
        calls.append((frame.asset + "_" + frame.timeframe, frame.observed_at))
        return _deterministic_provider(
            frame, config=config, provider_config=provider_config
        )

    records = study._replay_all(
        _synthetic_datasets(),
        config=config,
        provider_config=provider_config,
        selection_policy=selection,
        tracking_policy=tracking,
        provider=provider,
    )
    assert len(records) == 48
    assert len(calls) == 48
    assert [item[0] for item in calls[:8]] == ["BTCUSDT_1h"] * 8
    assert [item[0] for item in calls[8:16]] == ["BTCUSDT_4h"] * 8
    assert [item[0] for item in calls[16:24]] == ["ETHUSDT_1h"] * 8
    assert [item[0] for item in calls[24:32]] == ["ETHUSDT_4h"] * 8
    assert [item[0] for item in calls[32:40]] == ["SUIUSDT_1h"] * 8
    assert [item[0] for item in calls[40:48]] == ["SUIUSDT_4h"] * 8
    assert all(
        record.tracking_snapshot.diagnostics.source_removed_count == 0
        for record in records
    )
    assert all(
        record.tracking_snapshot.diagnostics.birth_count >= 0
        for record in records
    )


def test_dual_generation_guard_refuses_before_source_or_provider(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[str] = []
    monkeypatch.setattr(
        study,
        "_load_frozen_references",
        lambda _root: calls.append("source") or (_ for _ in ()).throw(
            AssertionError("source loaded before guard")
        ),
    )
    with pytest.raises(study.ReplayStudyError, match="execute-provider-replay"):
        study.build_study(output_root=tmp_path / "output")
    with pytest.raises(study.ReplayStudyError, match=study.NETWORK_ENV):
        study.build_study(
            output_root=tmp_path / "output-2",
            execute_provider_replay=True,
            environment={},
        )
    assert calls == []


def test_existing_output_root_is_refused_before_provider(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    output = tmp_path / "existing"
    output.mkdir()
    calls: list[str] = []
    monkeypatch.setattr(
        study,
        "_load_frozen_references",
        lambda _root: calls.append("source"),
    )
    with pytest.raises(FileExistsError):
        study.build_study(
            output_root=output,
            execute_provider_replay=True,
            environment={study.NETWORK_ENV: "1"},
        )
    assert calls == []


def test_staging_bootstrap_supports_missing_output_parent(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    output = tmp_path / "missing-parent" / "output"
    monkeypatch.setattr(
        study,
        "_load_frozen_references",
        lambda _root: study.FrozenReferences((), {}),
    )
    monkeypatch.setattr(
        study,
        "_replay_all",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            study.ReplayStudyError("synthetic replay stop")
        ),
    )
    with pytest.raises(study.ReplayStudyError, match="synthetic replay stop"):
        study.build_study(
            output_root=output,
            execute_provider_replay=True,
            environment={study.NETWORK_ENV: "1"},
        )
    assert output.parent.is_dir()
    assert not output.exists()


def test_provider_non_success_is_a_hard_scope_block() -> None:
    config, provider_config, _, _ = study._fixed_configuration()
    input_data = _synthetic_datasets()[0].full_input
    request = ProviderRequest(
        input_data=input_data,
        config=config,
        provider_config=provider_config,
    )
    failure = ProviderResult(
        provider_name=provider_config.provider_name,
        provider_version=provider_config.provider_version,
        request=request,
        status=ProviderStatus.FAILED,
        candidates=(),
        diagnostics=ProviderDiagnostics(
            candidate_count=0,
            input_row_count=input_data.row_count,
        ),
        reason=ProviderReason.PROVIDER_FAILURE,
    )
    with pytest.raises(study.ReplayScopeBlocked, match="BLOCKED_PROVIDER_SCOPE"):
        study._execute_provider(
            input_data,
            config=config,
            provider_config=provider_config,
            provider=lambda *_args, **_kwargs: failure,
        )


def test_atomic_write_refuses_non_identical_overwrite(tmp_path: Path) -> None:
    path = tmp_path / "nested" / "artifact.json"
    study._write_atomic(path, b"first\n")
    with pytest.raises(FileExistsError):
        study._write_atomic(path, b"second\n")
    assert path.read_bytes() == b"first\n"


def test_manifest_member_inventory_excludes_manifest(tmp_path: Path) -> None:
    (tmp_path / "a.json").write_bytes(b"{}\n")
    (tmp_path / "manifest.json").write_bytes(b"{}\n")
    members = study._member_inventory(tmp_path)
    assert [item["path"] for item in members] == ["a.json"]


def test_tracking_gate_rejects_removed_family_on_continuation() -> None:
    config, provider_config, selection, tracking = study._fixed_configuration()
    records = []

    def provider(frame, *, config, provider_config):
        return _deterministic_provider(
            frame, config=config, provider_config=provider_config
        )

    records = study._replay_dataset(
        _synthetic_datasets()[0],
        config=config,
        provider_config=provider_config,
        selection_policy=selection,
        tracking_policy=tracking,
        provider=provider,
    )
    previous = records[0].tracking_snapshot
    current = records[1].tracking_snapshot
    assert previous.active_families
    assert current.diagnostics.source_removed_count == 0
    assert current.diagnostics.continuation_count == len(previous.active_families)


@pytest.mark.parametrize("value", [True, False, "bad"])
def test_provider_config_remains_typed(value: object) -> None:
    with pytest.raises((ContractValidationError, TypeError, ValueError)):
        ConfirmedExtremaPairConfig(
            lookback_duration_seconds=value,
            left_confirmation_bars=1,
            right_confirmation_bars=1,
            min_extrema_per_role=2,
            max_hypotheses=100_000,
            max_output_candidates=10_000,
        )


def test_no_network_adapter_is_imported_by_replay_script() -> None:
    source = Path(study.__file__).read_text()
    assert "binance_native" not in source
    assert "requests" not in source
    assert "aiohttp" not in source


def test_offline_republication_path_does_not_call_provider(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    provider_calls: list[str] = []

    def unexpected_provider(*args: object, **kwargs: object) -> object:
        provider_calls.append("discover_trendlines")
        raise AssertionError("offline remediation called a provider")

    monkeypatch.setattr(study, "discover_trendlines", unexpected_provider)
    monkeypatch.setattr(
        study,
        "_load_frozen_references",
        lambda source_root: SimpleNamespace(source_audit={}),
    )
    monkeypatch.setattr(
        study,
        "_fixed_configuration",
        lambda: (None, None, None, None),
    )
    monkeypatch.setattr(
        study,
        "_load_superseded_records",
        lambda *args, **kwargs: (),
    )
    monkeypatch.setattr(
        study,
        "_build_source_audit_after",
        lambda *args, **kwargs: {},
    )
    monkeypatch.setattr(
        study,
        "_payloads",
        lambda *args, **kwargs: ({}, {}, None),
    )
    monkeypatch.setattr(study, "_assert_decision_gates", lambda *args, **kwargs: None)
    monkeypatch.setattr(study, "_write_payloads", lambda *args, **kwargs: None)
    monkeypatch.setattr(study, "_manifest", lambda *args, **kwargs: {})
    monkeypatch.setattr(study, "_write_json", lambda *args, **kwargs: None)
    monkeypatch.setattr(
        study,
        "_verify_bundle",
        lambda *args, **kwargs: {
            "study_status": "EXACT_TEMPORAL_REPLAY_VERIFIED",
            "records": (),
        },
    )

    result = study.republish_study(
        source_root=tmp_path / "source",
        superseded_root=tmp_path / "superseded",
        output_root=tmp_path / "output",
    )

    assert provider_calls == []
    assert result["remediation_provider_execution_count"] == 0
    assert result["remediation_network_request_count"] == 0
    assert (tmp_path / "output").is_dir()


@pytest.mark.skipif(
    os.environ.get("TRENDLINE_V2_VERIFY_EXTERNAL_EVIDENCE") != "1",
    reason="requires the verified external Phase 10B bundle",
)
def test_external_bundle_matches_exact_frozen_replay_evidence() -> None:
    verified = study.verify_study_bundle()
    assert verified == {
        "study_status": "EXACT_TEMPORAL_REPLAY_VERIFIED",
        "decision_id": "0b56ce796076cc6ff0f5f1dda962e3774e704915e82700e52c80103f983de4d7",
        "manifest_id": "5b4aabc2327fc0d37ba925a0fde7207072997edf517814d0db03e05442386927",
        "output_inventory_sha256": "f8fc8e223c3a7e9475e0c3fbcb8a9bf53f75cca678e589aee087eae213ad99dc",
        "checkpoint_contract_id": study.CHECKPOINT_CONTRACT_ID,
        "provider_execution_count": 48,
        "network_request_count": 0,
    }
    root = study.OUTPUT_ROOT
    audit = study._load_json(root / "provider_execution_audit.json")
    assert audit["provider_execution_count"] == 48
    assert audit["network_request_count"] == 0
    assert audit["retry_count"] == 0
    assert audit["fallback_count"] == 0
    assert audit["configuration_variant_count"] == 0
    assert audit["parallel_execution_count"] == 0
    assert [item["execution_order"] for item in audit["execution_order"]] == list(
        range(1, 49)
    )
    assert all(
        item["status"] == "success"
        and item["reason"] is None
        and item["provider_execution_count"] == 1
        for item in audit["execution_order"]
    )

    actual_rows = []
    for item in audit["execution_order"]:
        stamp = item["observed_at"].replace("-", "").replace(":", "")
        checkpoint_path = (
            root
            / "datasets"
            / item["dataset_id"]
            / f"checkpoint_{item['checkpoint_index']:02d}_{stamp}.json"
        )
        payload = study._load_json(checkpoint_path)
        tracking = payload["tracking_snapshot"]
        diagnostics = tracking["diagnostics"]
        actual_rows.append(
            (
                item["dataset_id"],
                item["checkpoint_index"],
                item["prefix_input_identity"],
                item["provider_result_id"],
                payload["discovery_snapshot_id"],
                payload["selection_snapshot"]["snapshot_id"],
                tracking["snapshot_id"],
                item["candidate_count"],
                len(payload["selection_snapshot"]["selected_candidates"]),
                len(tracking["active_families"]),
                diagnostics["birth_count"],
                diagnostics["continuation_count"],
                diagnostics["source_removed_count"],
            )
        )
    assert tuple(actual_rows) == EXPECTED_EXTERNAL_ROWS

    decision = study._load_json(root / "decision.json")
    assert decision["checkpoint_contract_id"] == study.CHECKPOINT_CONTRACT_ID
    assert decision["dataset_count"] == 6
    assert decision["checkpoints_per_dataset"] == 8
    assert decision["checkpoint_count"] == 48
    assert decision["phase10b_provider_executions"] == 48
    assert decision["provider_success_count"] == 48
    assert decision["source_unavailable_count"] == 0
    assert decision["source_removed_transition_count"] == 0
    assert decision["final_active_family_count"] == 1619
    assert decision["total_birth_count"] == 1619
    assert decision["final_phase9d_selection_parity"] is True
    assert decision["final_phase10a_family_parity"] is True
    assert decision["total_continuation_count"] == 6704
    assert decision["candidate_id_turnover_count"] == 6704
    assert {
        item["dataset_id"]: item["active_tracked_family_count"]
        for item in decision["datasets"]
    } == {
        "btcusdt_1h": 422,
        "btcusdt_4h": 106,
        "ethusdt_1h": 433,
        "ethusdt_4h": 109,
        "suiusdt_1h": 437,
        "suiusdt_4h": 112,
    }
    manifest = study._load_json(root / "manifest.json")
    assert manifest["manifest_id"] == verified["manifest_id"]
    assert manifest["decision_id"] == verified["decision_id"]
    assert manifest["member_count"] == 54
    assert manifest["source_inventories"] == {
        "phase9c1": study.PHASE9C1_INVENTORY_SHA256,
        "phase9d": study.PHASE9D_INVENTORY_SHA256,
        "phase10a": study.PHASE10A_INVENTORY_SHA256,
    }
    source_audit = study._load_json(root / "source_audit.json")
    assert {
        key: value["inventory_sha256"]
        for key, value in source_audit["source_roots"].items()
    } == manifest["source_inventories"]

    protected_paths = tuple(
        path.relative_to(root)
        for path in sorted(root.rglob("*"))
        if path.is_file()
        and path.name not in {"study_contract.json", "decision.json", "manifest.json"}
    )
    assert len(protected_paths) == 52
    assert study._inventory_sha256(
        study._inventory(study.SUPERSEDED_OUTPUT_ROOT)
    ) == study.SUPERSEDED_OUTPUT_INVENTORY_SHA256
    assert all(
        (root / relative).read_bytes()
        == (study.SUPERSEDED_OUTPUT_ROOT / relative).read_bytes()
        for relative in protected_paths
    )
