#pragma once
#include "loci/common.hpp"
#include <array>
#include <cstring>
#include <openssl/crypto.h>
#include <openssl/evp.h>
#include <openssl/hmac.h>
#include <openssl/rand.h>

namespace loci {

enum class CryptoMode {
    Mock,
    OpenSSL
};

enum class ObjectKind : std::uint64_t {
    Cell = 0xC311,
    Desc = 0xD35C,
    Proto = 0xA019,
    Full = 0xF011,
    Log = 0x1099,
    Pad = 0x9999
};

struct SealedObject {
    std::uint64_t tag = 0;
    std::size_t padded_size = 0;
    Bytes ciphertext;
};

struct PaddingPolicy {
    std::size_t desc_class = 128;
    std::size_t proto_class = 128;
    std::size_t patch_class = 64;
    std::size_t full_min_class = 64;

    std::size_t desc_pad() const { return desc_class; }
    std::size_t proto_pad() const { return proto_class; }
    std::size_t patch_pad() const { return patch_class; }
    std::size_t bitvec_pad(std::size_t bit_count) const {
        if (full_min_class == 0) return 0;
        return next_power_of_two(8 + (bit_count + 7) / 8, full_min_class);
    }
};

class MockCrypto {
    std::uint64_t key_ = 0;
    CryptoMode mode_ = CryptoMode::Mock;
    std::array<Byte, 32> prf_key_{};
    std::array<Byte, 32> enc_key_{};
public:
    explicit MockCrypto(std::uint64_t key, CryptoMode mode = CryptoMode::Mock) : key_(key), mode_(mode) {
        prf_key_ = derive_key("LOCI-PRF");
        enc_key_ = derive_key("LOCI-AEAD");
    }

    std::uint64_t prf(std::uint64_t domain, std::uint64_t x) const {
        if (mode_ == CryptoMode::OpenSSL) return openssl_prf64(domain, x);
        return splitmix64(key_ ^ (domain * 0x9e3779b97f4a7c15ULL) ^ x);
    }

    std::uint64_t handle(std::uint64_t nonce) const {
        return prf(static_cast<std::uint64_t>(ObjectKind::Cell), nonce);
    }

    std::uint64_t tag(std::uint64_t handle, ObjectKind kind, std::uint64_t index = 0) const {
        return prf(static_cast<std::uint64_t>(kind), handle ^ (index * 0xd6e8feb86659fd93ULL));
    }

    SealedObject seal(std::uint64_t tag, const Bytes& plaintext, std::size_t min_padded_size) const {
        if (mode_ == CryptoMode::OpenSSL) return openssl_seal(tag, plaintext, min_padded_size);
        std::size_t padded = (min_padded_size == 0) ? (8 + plaintext.size()) : next_power_of_two(8 + plaintext.size(), min_padded_size);
        Bytes padded_plain(padded, 0), ct(padded, 0);
        std::uint64_t len = plaintext.size();
        for (int i = 0; i < 8; ++i) padded_plain[i] = static_cast<Byte>((len >> (8 * i)) & 0xff);
        std::copy(plaintext.begin(), plaintext.end(), padded_plain.begin() + 8);
        stream_xor(tag, padded_plain, ct);
        return SealedObject{tag, padded, std::move(ct)};
    }

    Bytes open(const SealedObject& obj) const {
        if (mode_ == CryptoMode::OpenSSL) return openssl_open(obj);
        Bytes plain(obj.padded_size, 0);
        stream_xor(obj.tag, obj.ciphertext, plain);
        std::uint64_t len = 0;
        for (int i = 0; i < 8; ++i) len |= static_cast<std::uint64_t>(plain[i]) << (8 * i);
        if (8 + len > plain.size()) throw std::runtime_error("MockCrypto::open failed");
        return Bytes(plain.begin() + 8, plain.begin() + static_cast<long>(8 + len));
    }

    std::size_t sealed_size(std::size_t plaintext_size, std::size_t min_padded_size) const {
        std::size_t padded = (min_padded_size == 0)
            ? (8 + plaintext_size)
            : next_power_of_two(8 + plaintext_size, min_padded_size);
        if (mode_ == CryptoMode::OpenSSL) return padded + 12 + 16;
        return padded;
    }

private:
    std::array<Byte, 32> derive_key(const std::string& label) const {
        Bytes data(label.begin(), label.end());
        for (int i = 0; i < 8; ++i) data.push_back(static_cast<Byte>((key_ >> (8 * i)) & 0xff));
        unsigned int out_len = 0;
        std::array<Byte, 32> out{};
        const char* salt = "LOCI crypto seed";
        HMAC(EVP_sha256(),
             salt,
             static_cast<int>(std::strlen(salt)),
             data.data(),
             data.size(),
             out.data(),
             &out_len);
        if (out_len != out.size()) throw std::runtime_error("OpenSSL HMAC key derivation failed");
        return out;
    }

    Bytes hmac_sha256(const std::array<Byte, 32>& key, const Bytes& data) const {
        unsigned int out_len = 0;
        Bytes out(32, 0);
        HMAC(EVP_sha256(),
             key.data(),
             static_cast<int>(key.size()),
             data.data(),
             data.size(),
             out.data(),
             &out_len);
        if (out_len != out.size()) throw std::runtime_error("OpenSSL HMAC-SHA256 failed");
        return out;
    }

    std::uint64_t openssl_prf64(std::uint64_t domain, std::uint64_t x) const {
        ByteWriter w;
        w.u64(domain);
        w.u64(x);
        auto mac = hmac_sha256(prf_key_, w.data);
        std::uint64_t out = 0;
        for (int i = 0; i < 8; ++i) out |= static_cast<std::uint64_t>(mac[static_cast<std::size_t>(i)]) << (8 * i);
        return out;
    }

    SealedObject openssl_seal(std::uint64_t tag, const Bytes& plaintext, std::size_t min_padded_size) const {
        std::size_t padded = (min_padded_size == 0) ? (8 + plaintext.size()) : next_power_of_two(8 + plaintext.size(), min_padded_size);
        Bytes padded_plain(padded, 0);
        std::uint64_t len = plaintext.size();
        for (int i = 0; i < 8; ++i) padded_plain[static_cast<std::size_t>(i)] = static_cast<Byte>((len >> (8 * i)) & 0xff);
        std::copy(plaintext.begin(), plaintext.end(), padded_plain.begin() + 8);

        Bytes nonce(12, 0);
        if (RAND_bytes(nonce.data(), static_cast<int>(nonce.size())) != 1) throw std::runtime_error("OpenSSL RAND_bytes failed");

        Bytes ct(padded_plain.size(), 0);
        Bytes auth_tag(16, 0);
        EVP_CIPHER_CTX* ctx = EVP_CIPHER_CTX_new();
        if (!ctx) throw std::runtime_error("OpenSSL EVP_CIPHER_CTX_new failed");

        auto fail = [&]() {
            EVP_CIPHER_CTX_free(ctx);
            throw std::runtime_error("OpenSSL AES-256-GCM seal failed");
        };

        int out_len = 0;
        int total = 0;
        if (EVP_EncryptInit_ex(ctx, EVP_aes_256_gcm(), nullptr, nullptr, nullptr) != 1) fail();
        if (EVP_CIPHER_CTX_ctrl(ctx, EVP_CTRL_GCM_SET_IVLEN, static_cast<int>(nonce.size()), nullptr) != 1) fail();
        if (EVP_EncryptInit_ex(ctx, nullptr, nullptr, enc_key_.data(), nonce.data()) != 1) fail();
        ByteWriter aad;
        aad.u64(tag);
        if (EVP_EncryptUpdate(ctx, nullptr, &out_len, aad.data.data(), static_cast<int>(aad.data.size())) != 1) fail();
        if (EVP_EncryptUpdate(ctx, ct.data(), &out_len, padded_plain.data(), static_cast<int>(padded_plain.size())) != 1) fail();
        total += out_len;
        if (EVP_EncryptFinal_ex(ctx, ct.data() + total, &out_len) != 1) fail();
        total += out_len;
        ct.resize(static_cast<std::size_t>(total));
        if (EVP_CIPHER_CTX_ctrl(ctx, EVP_CTRL_GCM_GET_TAG, static_cast<int>(auth_tag.size()), auth_tag.data()) != 1) fail();
        EVP_CIPHER_CTX_free(ctx);

        Bytes sealed;
        sealed.reserve(nonce.size() + auth_tag.size() + ct.size());
        sealed.insert(sealed.end(), nonce.begin(), nonce.end());
        sealed.insert(sealed.end(), auth_tag.begin(), auth_tag.end());
        sealed.insert(sealed.end(), ct.begin(), ct.end());
        return SealedObject{tag, sealed.size(), std::move(sealed)};
    }

    Bytes openssl_open(const SealedObject& obj) const {
        constexpr std::size_t nonce_len = 12;
        constexpr std::size_t auth_tag_len = 16;
        if (obj.ciphertext.size() < nonce_len + auth_tag_len) throw std::runtime_error("OpenSSL sealed object truncated");
        const Byte* nonce = obj.ciphertext.data();
        const Byte* auth_tag = obj.ciphertext.data() + nonce_len;
        const Byte* ct = obj.ciphertext.data() + nonce_len + auth_tag_len;
        std::size_t ct_len = obj.ciphertext.size() - nonce_len - auth_tag_len;
        Bytes plain(ct_len, 0);

        EVP_CIPHER_CTX* ctx = EVP_CIPHER_CTX_new();
        if (!ctx) throw std::runtime_error("OpenSSL EVP_CIPHER_CTX_new failed");
        auto fail = [&]() {
            EVP_CIPHER_CTX_free(ctx);
            throw std::runtime_error("OpenSSL AES-256-GCM open failed");
        };

        int out_len = 0;
        int total = 0;
        if (EVP_DecryptInit_ex(ctx, EVP_aes_256_gcm(), nullptr, nullptr, nullptr) != 1) fail();
        if (EVP_CIPHER_CTX_ctrl(ctx, EVP_CTRL_GCM_SET_IVLEN, static_cast<int>(nonce_len), nullptr) != 1) fail();
        if (EVP_DecryptInit_ex(ctx, nullptr, nullptr, enc_key_.data(), nonce) != 1) fail();
        ByteWriter aad;
        aad.u64(obj.tag);
        if (EVP_DecryptUpdate(ctx, nullptr, &out_len, aad.data.data(), static_cast<int>(aad.data.size())) != 1) fail();
        if (EVP_DecryptUpdate(ctx, plain.data(), &out_len, ct, static_cast<int>(ct_len)) != 1) fail();
        total += out_len;
        if (EVP_CIPHER_CTX_ctrl(ctx, EVP_CTRL_GCM_SET_TAG, static_cast<int>(auth_tag_len), const_cast<Byte*>(auth_tag)) != 1) fail();
        int ok = EVP_DecryptFinal_ex(ctx, plain.data() + total, &out_len);
        EVP_CIPHER_CTX_free(ctx);
        if (ok != 1) throw std::runtime_error("OpenSSL AES-256-GCM authentication failed");
        total += out_len;
        plain.resize(static_cast<std::size_t>(total));

        if (plain.size() < 8) throw std::runtime_error("OpenSSL plaintext truncated");
        std::uint64_t len = 0;
        for (int i = 0; i < 8; ++i) len |= static_cast<std::uint64_t>(plain[static_cast<std::size_t>(i)]) << (8 * i);
        if (8 + len > plain.size()) throw std::runtime_error("OpenSSL plaintext length invalid");
        return Bytes(plain.begin() + 8, plain.begin() + static_cast<long>(8 + len));
    }

    void stream_xor(std::uint64_t tag, const Bytes& in, Bytes& out) const {
        if (out.size() != in.size()) out.resize(in.size());
        std::uint64_t block = 0;
        std::uint64_t ctr = 0;
        int off = 8;
        for (std::size_t i = 0; i < in.size(); ++i) {
            if (off == 8) {
                block = splitmix64(key_ ^ tag ^ (++ctr * 0x9e3779b97f4a7c15ULL));
                off = 0;
            }
            out[i] = static_cast<Byte>(in[i] ^ ((block >> (8 * off)) & 0xff));
            ++off;
        }
    }
};

} // namespace loci
