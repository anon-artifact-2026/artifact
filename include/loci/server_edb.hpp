#pragma once
#include "loci/crypto.hpp"

namespace loci {

struct FetchRef {
    std::uint64_t tag = 0;
};

struct QueryToken {
    std::vector<FetchRef> refs;
};

struct QueryResponse {
    std::map<std::uint64_t, SealedObject> objects;
};

class ServerEDB {
    std::map<std::uint64_t, SealedObject> objects_;
    std::map<std::uint64_t, std::set<std::uint64_t>> cell_tags_;
public:
    void put(std::uint64_t handle, const SealedObject& obj) {
        objects_[obj.tag] = obj;
        cell_tags_[handle].insert(obj.tag);
    }
    void erase_cell(std::uint64_t handle) {
        auto it = cell_tags_.find(handle);
        if (it == cell_tags_.end()) return;
        for (auto tag : it->second) objects_.erase(tag);
        cell_tags_.erase(it);
    }
    bool has(std::uint64_t tag) const { return objects_.count(tag) != 0; }
    const SealedObject& fetch(std::uint64_t tag) const {
        auto it = objects_.find(tag);
        if (it == objects_.end()) throw std::runtime_error("ServerEDB: missing tag");
        return it->second;
    }
    QueryResponse fetch(const QueryToken& token) const {
        QueryResponse ans;
        for (const auto& ref : token.refs) {
            ans.objects[ref.tag] = fetch(ref.tag);
        }
        return ans;
    }
    std::size_t byte_size() const {
        std::size_t n = 0;
        for (const auto& [_, obj] : objects_) n += obj.padded_size;
        return n;
    }
    std::size_t object_count() const { return objects_.size(); }
};

} // namespace loci
