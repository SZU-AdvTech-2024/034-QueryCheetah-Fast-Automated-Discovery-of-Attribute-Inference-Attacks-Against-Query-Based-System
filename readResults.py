import pickle

# 指定文件路径
file_path = 'results/qc_dn-adult_dcc-0_ncc-5_iters-5000_utuv-1_nprocs-10-_in-0_bw-0_mt-0_nin-0_cq-1_at-aia_ols-1_lsfq-0_ph-0_tui-0_rep-0'

# 打开文件并读取内容
with open(file_path, 'rb') as f:
    results = pickle.load(f)

# 查看读取的数据
print(results)
